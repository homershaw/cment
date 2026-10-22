"""API, engine, alarms, batch records and batch control against the simulated PLC."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from scada import auth
from scada.app import create_app
from scada.config import Config
from scada.engine import Engine
from scada.s7 import S7Link
from scada.store import Store
from sim.plant import Plant
from sim.server import PlcServer
from tests.test_plc_link import free_port


@pytest.fixture()
def rig(tmp_path):
    port = free_port()
    server = PlcServer()
    plant = Plant(server, auto_every=0, faults=False, seed=2)
    server.start(tcp_port=port)
    cfg = Config(plc_port=port, db_path=tmp_path / "t.db", control_enabled=True, sample_s=0)
    store = Store(cfg.db_path)
    auth.add_user(store, "op", "secret1", "operator")
    auth.add_user(store, "view", "secret1", "viewer")
    engine = Engine(cfg, store, S7Link("127.0.0.1", 0, 1, port))
    client = TestClient(create_app(cfg, store, engine, start_engine=False))

    def tick(seconds=1.0, dt=0.5):
        for _ in range(max(1, int(seconds / dt))):
            plant.step(dt)
            engine.poll_once()

    yield plant, engine, client, tick, cfg, store
    engine.link.close()
    server.stop()
    server.destroy()


def login(client, name="op"):
    r = client.post("/api/login", json={"username": name, "password": "secret1"})
    assert r.status_code == 200


def test_snapshot_and_meta(rig):
    plant, engine, client, tick, *_ = rig
    tick()
    snap = client.get("/api/snapshot").json()
    assert snap["connected"] and snap["values"]["plant.ready"] is True
    meta = client.get("/api/meta").json()
    assert any(t["address"] == "DB9.DBD14" for t in meta["tags"])


def test_websocket_pushes_snapshot(rig):
    plant, engine, client, tick, *_ = rig
    tick()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["connected"] is True


def test_control_needs_operator_login(rig):
    plant, engine, client, tick, *_ = rig
    tick()
    assert client.post("/api/control/start", json={"quantity": 1}).status_code == 401
    login(client, "view")
    assert client.post("/api/control/start", json={"quantity": 1}).status_code == 403


def test_control_disabled_refuses(rig):
    plant, engine, client, tick, cfg, store = rig
    tick()
    login(client)
    cfg.control_enabled = False
    r = client.post("/api/control/start", json={"quantity": 1})
    assert r.status_code == 409 and "disabled" in r.json()["detail"]


def test_batch_start_to_complete_is_recorded(rig):
    plant, engine, client, tick, cfg, store = rig
    tick()
    login(client)
    assert client.post("/api/control/start", json={"quantity": 99}).status_code == 409  # out of range
    r = client.post("/api/control/start", json={"quantity": 1.5})
    assert r.status_code == 200, r.text
    assert client.post("/api/control/start", json={"quantity": 1.5}).status_code == 409  # already running
    tick(150)
    batches = client.get("/api/batches").json()
    assert len(batches) == 1 and batches[0]["status"] == "complete"
    mats = batches[0]["detail"]["materials"]
    assert mats["bin1"]["batched"] == pytest.approx(1200, rel=0.02)
    assert set(mats) >= {"bin1", "bin2", "bin3", "silo1", "silo2", "water", "adx1"}
    csv = client.get("/api/batches.csv").text
    assert "Agg 1" in csv and "complete" in csv
    actions = [e["action"] for e in client.get("/api/events").json()]
    assert "control.start" in actions and "batch.complete" in actions
    # The simulation runs much faster than real time, so ask for the batch's own span.
    b = batches[0]
    series = client.get("/api/trends", params={"keys": "bin1.current", "t0": b["started"] - 1,
                                               "t1": b["ended"] + 1, "points": 1000}).json()["series"]["bin1.current"]
    assert len(series) > 3
    assert series[0]["avg"] > series[-1]["avg"]  # the bin was emptied by the batch


def test_pause_resume_abort(rig):
    plant, engine, client, tick, *_ = rig
    tick()
    login(client)
    assert client.post("/api/control/pause").status_code == 409  # nothing running
    client.post("/api/control/start", json={"quantity": 1})
    tick(8)
    assert client.post("/api/control/pause").status_code == 200
    tick(1)
    assert engine.values["batch.pause"] is True
    assert client.post("/api/control/resume").status_code == 200
    tick(1)
    assert engine.values["batch.pause"] is False
    assert client.post("/api/control/abort").status_code == 200
    tick(2)
    b = client.get("/api/batches").json()[0]
    assert b["status"] == "aborted"


def test_alarm_raise_ack_clear(rig):
    plant, engine, client, tick, *_ = rig
    plant.set("plant.estop_healthy", False)
    tick()
    active = client.get("/api/snapshot").json()["alarms"]
    assert [a["text"] for a in active] == ["E-stop fault"]
    login(client)
    assert client.post(f"/api/alarms/{active[0]['id']}/ack").status_code == 200
    plant.set("plant.estop_healthy", True)
    tick()
    assert client.get("/api/snapshot").json()["alarms"] == []
    hist = client.get("/api/alarms").json()
    assert hist[0]["cleared"] and hist[0]["acked_by"] == "op"


def test_plc_loss_raises_comm_alarm(rig):
    plant, engine, client, tick, *_ = rig
    tick()
    engine.link.port = 1  # nothing listens there
    engine.link.client.disconnect()
    engine.poll_once()
    snap = client.get("/api/snapshot").json()
    assert snap["connected"] is False
    assert any(a["key"] == "scada.plc_comm" for a in snap["alarms"])
