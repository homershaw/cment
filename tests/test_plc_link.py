"""The S7 link against the simulated PLC: block reads, decoding, bit writes and a full batch."""
import socket
import struct

import pytest

from scada.s7 import S7Link, decode, plan_blocks
from scada.tags import BY_KEY, TAGS, check_unique
from sim.plant import Plant
from sim.server import PlcServer


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def plc():
    port = free_port()
    server = PlcServer()
    plant = Plant(server, auto_every=0, faults=False, seed=1)
    server.start(tcp_port=port)
    link = S7Link("127.0.0.1", 0, 1, port)
    yield plant, link
    link.close()
    server.stop()
    server.destroy()


def run(plant, seconds, dt=0.5):
    for _ in range(int(seconds / dt)):
        plant.step(dt)


def test_tag_map_has_no_overlaps():
    check_unique()


def test_decode_real_and_bits():
    data = struct.pack(">f", 1234.5) + bytes([0b00010000])
    real = BY_KEY["bin1.current"]
    assert decode(real, data, real.byte) == 1234.5
    blocks = {(b.area, b.db): b for b in plan_blocks(TAGS)}
    assert blocks[("DB", 9)].start == 0 and blocks[("DB", 9)].size == 226


def test_read_all_matches_simulator(plc):
    plant, link = plc
    v = link.read_all()
    assert len(v) == len(TAGS)
    assert v["bin1.current"] == pytest.approx(plant.get("bin1.current"))
    assert v["plant.ready"] is True
    assert v["adx.count"] == 6


def test_bit_write_leaves_neighbours(plc):
    plant, link = plc
    plant.set("batch.klaxon", True)        # DB30.DBX16.1, same byte as Run_Batch (16.4)
    link.write("batch.pause", True)        # DB30.DBX16.5
    assert plant.get("batch.pause") is True
    assert plant.get("batch.klaxon") is True
    link.write("batch.pause", False)
    assert plant.get("batch.pause") is False
    assert plant.get("batch.klaxon") is True


def test_only_batch_tags_are_writable(plc):
    _, link = plc
    with pytest.raises(Exception):
        link.write("out.main_conv", True)


def test_full_batch_via_link(plc):
    plant, link = plc
    link.write("batch.quantity", 1.5)
    link.write("batch.run", True)
    run(plant, 1)
    assert link.read_all()["batch.stage"] == 1
    run(plant, 120)
    v = link.read_all()
    assert v["batch.stage"] == 0 and v["batch.run"] is False
    assert v["bin1.batched"] == pytest.approx(800 * 1.5, rel=0.02)
    assert v["silo1.batched"] == pytest.approx(280 * 1.5, rel=0.02)
    assert v["bin1.complete"] and v["water.tail_complete"]


def test_pause_and_resume(plc):
    plant, link = plc
    link.write("batch.run", True)
    run(plant, 8)
    assert plant.get("batch.stage") == 2
    link.write("batch.pause", True)
    before = plant.get("bin1.current")
    run(plant, 5)
    assert plant.get("bin1.current") == before
    link.write("batch.resume", True)
    run(plant, 1)
    assert plant.get("batch.pause") is False and plant.get("batch.resume") is False
    assert plant.get("bin1.current") < before


def test_abort(plc):
    plant, link = plc
    link.write("batch.run", True)
    run(plant, 8)
    link.write("batch.abort", True)
    run(plant, 1)
    assert plant.get("batch.stage") == 0 and plant.get("batch.abort") is False
