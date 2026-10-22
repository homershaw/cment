"""HTTP API, WebSocket live feed and the static web screens."""
import asyncio
import csv
import io
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth
from .config import ROOT, Config
from .control import Control, ControlError
from .engine import Engine
from .store import Store
from .tags import BY_KEY, TAGS, TREND_TAGS

COOKIE = "scada_session"
WEB = ROOT / "web"


class LoginIn(BaseModel):
    username: str
    password: str


class StartIn(BaseModel):
    quantity: float


def create_app(cfg: Config, store: Store, engine: Engine, start_engine: bool = True) -> FastAPI:
    control = Control(cfg, engine)

    @asynccontextmanager
    async def lifespan(app):
        if start_engine:
            engine.start()
            store.event("scada.started", f"PLC {cfg.plc_host}:{cfg.plc_port}")
        yield
        if start_engine:
            engine.stop()
            store.event("scada.stopped")

    app = FastAPI(title="cment batch plant SCADA", lifespan=lifespan)

    def user(request: Request):
        return auth.session_user(store, request.cookies.get(COOKIE))

    def operator(request: Request):
        u = user(request)
        if not u:
            raise HTTPException(401, "Log in to do this")
        if u["role"] not in ("operator", "admin"):
            raise HTTPException(403, "Operator role required")
        return u

    # --- session ---
    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        token = auth.login(store, body.username.strip(), body.password)
        if not token:
            store.event("user.login", f"failed for {body.username!r}", ok=False)
            raise HTTPException(401, "Wrong username or password")
        store.event("user.login", "", body.username)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_S)
        return auth.session_user(store, token)

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        auth.logout(store, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(u=Depends(user)):
        return u or {}

    # --- live data ---
    @app.get("/api/meta")
    def meta():
        return {
            "tags": [{"key": t.key, "label": t.label, "unit": t.unit, "group": t.group, "type": t.type,
                      "address": t.address, "decimals": t.decimals, "trend": t.trend} for t in TAGS],
            "stages": cfg.stages,
            "control": {"enabled": cfg.control_enabled, "min_quantity": cfg.min_quantity,
                        "max_quantity": cfg.max_quantity},
            "plc": {"host": cfg.plc_host, "rack": cfg.plc_rack, "slot": cfg.plc_slot, "port": cfg.plc_port,
                    "poll_ms": cfg.poll_ms},
        }

    @app.get("/api/snapshot")
    def snapshot():
        return engine.snapshot()

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        seen = -1
        try:
            while True:
                snap = engine.snapshot()
                if snap["version"] != seen:
                    seen = snap["version"]
                    await socket.send_json(snap)
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # --- alarms ---
    @app.get("/api/alarms")
    def alarms(hours: float = 24, limit: int = 500):
        return store.q("SELECT * FROM alarms WHERE raised >= ? ORDER BY raised DESC LIMIT ?",
                       (time.time() - hours * 3600, min(limit, 5000)))

    @app.post("/api/alarms/{alarm_id}/ack")
    def ack(alarm_id: int, u=Depends(operator)):
        if not engine.ack(alarm_id, u["username"]):
            raise HTTPException(404, "Alarm not found or already acknowledged")
        return {"ok": True}

    @app.post("/api/alarms/ack-all")
    def ack_all(u=Depends(operator)):
        for a in list(engine.active_alarms.values()):
            if not a["acked"]:
                engine.ack(a["id"], u["username"])
        return {"ok": True}

    # --- trends ---
    @app.get("/api/trends")
    def trends(keys: str, t0: float | None = None, t1: float | None = None, points: int = 600):
        t1 = t1 or time.time()
        t0 = t0 or t1 - 3600
        out = {}
        for k in keys.split(",")[:8]:
            if k not in BY_KEY or not BY_KEY[k].trend:
                raise HTTPException(400, f"{k} is not a trend tag")
            out[k] = store.series(k, t0, t1, max(10, min(points, 2000)))
        return {"t0": t0, "t1": t1, "series": out}

    @app.get("/api/trend-tags")
    def trend_tags():
        return [{"key": t.key, "label": f"{t.group} {t.label}", "unit": t.unit} for t in TREND_TAGS]

    # --- batches ---
    @app.get("/api/batches")
    def batches(days: float = 7, limit: int = 200):
        return store.batches(time.time() - days * 86400, limit=min(limit, 5000))

    @app.get("/api/batches.csv")
    def batches_csv(days: float = 30):
        rows = store.batches(time.time() - days * 86400, limit=100000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["batch", "started", "ended", "status", "quantity_m3", "material", "unit",
                    "required", "batched", "accuracy_pct", "out_of_tolerance"])
        for b in rows:
            started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b["started"]))
            ended = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b["ended"])) if b["ended"] else ""
            mats = b["detail"].get("materials", {}) or {"": {}}
            for m in mats.values():
                w.writerow([b["id"], started, ended, b["status"], b["quantity"], m.get("label", ""),
                            m.get("unit", ""), m.get("required"), m.get("batched"), m.get("accuracy"),
                            "yes" if m.get("over_tol") or m.get("under_tol") else ""])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=batches.csv"})

    # --- events (audit) ---
    @app.get("/api/events")
    def events(hours: float = 72, limit: int = 500):
        return store.q("SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                       (time.time() - hours * 3600, min(limit, 5000)))

    # --- batch control ---
    def act(fn, *args):
        try:
            fn(*args)
        except ControlError as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.post("/api/control/start")
    def start(body: StartIn, u=Depends(operator)):
        return act(control.start, u["username"], body.quantity)

    @app.post("/api/control/pause")
    def pause(u=Depends(operator)):
        return act(control.pause, u["username"])

    @app.post("/api/control/resume")
    def resume(u=Depends(operator)):
        return act(control.resume, u["username"])

    @app.post("/api/control/abort")
    def abort(u=Depends(operator)):
        return act(control.abort, u["username"])

    # --- screens ---
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
