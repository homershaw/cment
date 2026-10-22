"""The poll loop: read the PLC, keep the live snapshot, record history, alarms and batches."""
import logging
import threading
import time

from .config import Config
from .s7 import PlcError, S7Link
from .store import Store
from .tags import ADX, ALARM_TAGS, BINS, BY_KEY, SILOS, TREND_TAGS

log = logging.getLogger(__name__)

# Alarms the SCADA derives itself, in addition to the PLC's Alarm_Data bits.
DERIVED_ALARMS = {
    "scada.plc_comm": "PLC communication lost",
    "scada.pause_oot": "Batch paused: out of tolerance",
    "scada.estop_popup": "E-stop pressed during a batch",
}
HEARTBEAT_S = 300.0   # store an unchanged trend value at least this often
DEADBAND = 0.002      # relative change that counts as a new trend value


class Engine:
    def __init__(self, cfg: Config, store: Store, link: S7Link | None = None):
        self.cfg, self.store = cfg, store
        self.link = link or S7Link(cfg.plc_host, cfg.plc_rack, cfg.plc_slot, cfg.plc_port)
        self.values: dict = {}
        self.ts = 0.0
        self.connected = False
        self.error: str | None = None
        self.poll_ms = 0.0
        self.version = 0
        self.active_alarms: dict[str, dict] = {}
        self.batch: dict | None = None
        self._last_sample: dict[str, tuple[float, float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._restore()

    # --- lifecycle ---
    def start(self):
        self._thread = threading.Thread(target=self._run, name="plc-poll", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.link.close()

    def _restore(self):
        for a in self.store.q("SELECT * FROM alarms WHERE cleared IS NULL"):
            self.active_alarms[a["key"]] = a
        running = self.store.q("SELECT * FROM batches WHERE status = 'running'")
        for b in running:  # left open by a previous run; decided on the first good poll
            self.batch = {"id": b["id"], "started": b["started"], "quantity": b["quantity"],
                          "aborted": False, "paused": False, "restored": True, "materials": {}}

    def _run(self):
        last_purge = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            self.poll_once()
            if time.time() - last_purge > 3600:
                last_purge = time.time()
                self.store.purge(self.cfg.keep_days)
            self._stop.wait(max(0.05, self.cfg.poll_ms / 1000 - (time.monotonic() - t0)))

    # --- one poll ---
    def poll_once(self):
        t0 = time.monotonic()
        try:
            values = self.link.read_all()
        except PlcError as e:
            with self._lock:
                if self.connected or self.error is None:
                    self.store.event("plc.disconnected", str(e), ok=False)
                self.connected, self.error = False, str(e)
                self.version += 1
            self._alarm("scada.plc_comm", True, DERIVED_ALARMS["scada.plc_comm"])
            return
        now = time.time()
        with self._lock:
            if not self.connected:
                self.store.event("plc.connected", f"{self.cfg.plc_host}:{self.cfg.plc_port}")
            self.values, self.ts, self.connected, self.error = values, now, True, None
            self.poll_ms = (time.monotonic() - t0) * 1000
            self.version += 1
        self._alarm("scada.plc_comm", False)
        self._alarms(values)
        self._batches(values, now)
        self._history(values, now)

    def _history(self, v: dict, now: float):
        due = {}
        for t in TREND_TAGS:
            val = v.get(t.key)
            if val is None:
                continue
            # Store on change (beyond a deadband, at most every sample_s) plus a slow heartbeat,
            # so an idle plant does not fill the database with identical values.
            last = self._last_sample.get(t.key)
            if last is None:
                store = True
            else:
                age, changed = now - last[0], abs(val - last[1]) > max(abs(last[1]) * DEADBAND, 10 ** -t.decimals)
                store = age >= HEARTBEAT_S or (changed and age >= self.cfg.sample_s)
            if store:
                due[t.key] = val
                self._last_sample[t.key] = (now, val)
        if due:
            self.store.add_samples(now, due)

    # --- alarms ---
    def _alarms(self, v: dict):
        for t in ALARM_TAGS:
            self._alarm(t.key, bool(v.get(t.key)), t.label)
        self._alarm("scada.pause_oot", bool(v.get("batch.pause_oot")), DERIVED_ALARMS["scada.pause_oot"])
        self._alarm("scada.estop_popup", bool(v.get("batch.estop_popup")), DERIVED_ALARMS["scada.estop_popup"])

    def _alarm(self, key: str, on: bool, text: str = ""):
        now = time.time()
        with self._lock:
            active = self.active_alarms.get(key)
            if on and not active:
                aid = self.store.x("INSERT INTO alarms (key, text, raised) VALUES (?, ?, ?)", (key, text, now))
                self.active_alarms[key] = {"id": aid, "key": key, "text": text, "raised": now,
                                           "cleared": None, "acked": None, "acked_by": None}
                self.version += 1
            elif not on and active:
                self.store.x("UPDATE alarms SET cleared = ? WHERE id = ?", (now, active["id"]))
                del self.active_alarms[key]
                self.version += 1

    def ack(self, alarm_id: int, user: str) -> bool:
        now = time.time()
        with self._lock:
            n = self.store.q("SELECT id FROM alarms WHERE id = ? AND acked IS NULL", (alarm_id,))
            if not n:
                return False
            self.store.x("UPDATE alarms SET acked = ?, acked_by = ? WHERE id = ?", (now, user, alarm_id))
            for a in self.active_alarms.values():
                if a["id"] == alarm_id:
                    a["acked"], a["acked_by"] = now, user
            self.version += 1
        return True

    # --- batch tracking (by process stage; the PLC's complete pulse is too short to poll) ---
    def _batches(self, v: dict, now: float):
        stage = v.get("batch.stage") or 0
        b = self.batch
        if b and b.get("restored"):
            b.pop("restored")
            if stage == 0:  # it finished while the SCADA was down; the outcome is unknown
                self.store.batch_update(b["id"], {"materials": {}, "note": "SCADA was offline when this batch ended"},
                                        status="unknown", ended=now)
                self.batch = b = None
        if stage != 0 and b is None:
            self.batch = b = {"started": now, "quantity": v.get("batch.quantity"), "aborted": False,
                              "paused": False, "materials": {}}
            b["id"] = self.store.batch_open(now, b["quantity"], {"materials": {}})
            b["saved"] = now
            self.store.event("batch.started", f"batch {b['id']}, {b['quantity'] or 0:.2f} m3")
        if b is None:
            return
        if stage != 0:
            b["aborted"] |= bool(v.get("batch.abort"))
            b["paused"] |= bool(v.get("batch.pause") or v.get("batch.pause_oot"))
            b["materials"] = materials(v)
            if now - b.get("saved", 0) >= 10:  # keep the open row current in case the SCADA stops
                b["saved"] = now
                self.store.batch_update(b["id"], self._detail(b))
            return
        status = "aborted" if b["aborted"] or not all(m["complete"] for m in b["materials"].values()) else "complete"
        self.store.batch_update(b["id"], self._detail(b), status=status, ended=now)
        self.store.event(f"batch.{status}", f"batch {b['id']}")
        self.batch = None

    @staticmethod
    def _detail(b):
        return {"materials": b["materials"], "paused": b["paused"]}

    # --- snapshot for the web ---
    def snapshot(self) -> dict:
        with self._lock:
            b = self.batch
            return {
                "ts": self.ts, "connected": self.connected, "error": self.error,
                "poll_ms": round(self.poll_ms, 1), "version": self.version,
                "values": self.values,
                "alarms": sorted(self.active_alarms.values(), key=lambda a: -a["raised"]),
                "batch": {"id": b["id"], "started": b["started"], "quantity": b["quantity"]} if b and "id" in b else None,
            }


def materials(v: dict) -> dict:
    """Required vs batched for every material in use during this batch."""
    out = {}
    for n in BINS:
        if (v.get(f"bin{n}.required") or 0) > 0:
            out[f"bin{n}"] = _mat(f"Agg {n}", "kg", v, f"bin{n}", v.get(f"bin{n}.batched"))
    for n in SILOS:
        if (v.get(f"silo{n}.required") or 0) > 0:
            out[f"silo{n}"] = _mat(f"Silo {n}", "kg", v, f"silo{n}", v.get(f"silo{n}.batched"))
    if (v.get("water.required") or 0) > 0:
        batched = (v.get("water.head_level") or 0) + (v.get("water.tail_level") or 0)
        out["water"] = _mat("Water", "L", v, "water", batched,
                            complete=bool(v.get("water.tail_complete") or (v.get("water.skip_tail") and v.get("water.head_complete"))))
    for n in ADX:
        if v.get(f"adx{n}.used") and (v.get(f"adx{n}.required") or 0) > 0:
            out[f"adx{n}"] = _mat(f"Admix {n}", "L", v, f"adx{n}", v.get(f"adx{n}.level"),
                                  complete=bool(v.get(f"adx{n}.complete") or v.get(f"adx{n}.filled")))
    return out


def _mat(label, unit, v, p, batched, complete=None):
    return {"label": label, "unit": unit, "required": v.get(f"{p}.required"), "batched": batched,
            "accuracy": v.get(f"{p}.accuracy"),
            "over_tol": bool(v.get(f"{p}.over_tol")), "under_tol": bool(v.get(f"{p}.under_tol")),
            "complete": bool(v.get(f"{p}.complete")) if complete is None else complete}
