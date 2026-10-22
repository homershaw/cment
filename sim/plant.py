"""A simple batch plant model behind the simulated PLC.

It is not a copy of the PLC program. It produces believable values in the real DB
layout so the SCADA can be built and tested without a plant:
  stage 0 idle -> 1 klaxon -> 2 batching -> 3 belt run-on -> 0 (batch complete)
The stage numbers are an assumption; the real program's "Proccess stage" values
must be confirmed on the PLC.

Batch commands follow the program listing:
  Run_Batch (DB30.DBX16.4) starts a batch when Ready To Run; the PLC resets it on completion.
  Pause Batch (DB30.DBX16.5) holds the batch; clearing it continues.
  Resume (DB30.DBX10.6) clears a pause, including an out-of-tolerance pause.
  Abort Button (DB30.DBX10.4) ends the batch; it is reset at stage 0.
"""
import random
import struct

from snap7.type import SrvArea

from scada.tags import ADX, BINS, BY_KEY, SILOS, TAGS

# Mix design per m3 (fictitious): kg for bins and silos, litres for water and admix.
MIX = {"bin1": 800.0, "bin2": 700.0, "bin3": 300.0, "silo1": 280.0, "silo2": 60.0,
       "water": 160.0, "adx1": 1.2, "adx2": 0.8, "adx3": 0.5}
BIN_FULL, SILO_FULL = 40000.0, 25000.0
GATE_RATE, AUGER_RATE, WATER_RATE, ADX_RATE = 120.0, 25.0, 6.0, 0.15  # per second
FREE_FALL = {"bin": 40.0, "silo": 8.0}


class Plant:
    def __init__(self, server, auto_every: float = 0.0, faults: bool = False, seed=None):
        self.server = server
        self.rng = random.Random(seed)
        self.auto_every, self.faults = auto_every, faults
        self.mem: dict = {}
        sizes: dict = {}
        for t in TAGS:
            k = (t.area, t.db)
            sizes[k] = max(sizes.get(k, 0), t.byte + t.size)
        for (area, db), size in sizes.items():
            buf = bytearray(size + 8)
            self.mem[(area, db)] = buf
            server.register_area(_srv_area(area), db, buf)
        self.t = 0.0
        self.stage_t = 0.0
        self.idle_t = 0.0
        self.paused_t = 0.0
        self.fault_bin = None
        self._init_values()

    # --- memory access in the real layout ---
    def get(self, key):
        t = BY_KEY[key]
        m = self.mem[(t.area, t.db)]
        if t.type == "bool":
            return bool(m[t.byte] >> t.bit & 1)
        fmt = {"int": ">h", "word": ">H", "dint": ">i", "real": ">f"}[t.type]
        return struct.unpack_from(fmt, m, t.byte)[0]

    def set(self, key, value):
        t = BY_KEY[key]
        m = self.mem[(t.area, t.db)]
        if t.type == "bool":
            if value:
                m[t.byte] |= 1 << t.bit
            else:
                m[t.byte] &= ~(1 << t.bit) & 0xFF
        else:
            fmt = {"int": ">h", "word": ">H", "dint": ">i", "real": ">f"}[t.type]
            struct.pack_into(fmt, m, t.byte, int(value) if t.type != "real" else float(value))

    def _init_values(self):
        s = self.set
        for n in BINS:
            s(f"bin{n}.current", BIN_FULL - n * 3000)
            s(f"bin{n}.tolerance", 2.0)
            s(f"bin{n}.overlap", 10)
            s(f"bin{n}.vib_mode", 1)
            s(f"bin{n}.gate_mode", 1)
        for n in SILOS:
            s(f"silo{n}.current", SILO_FULL - n * 2000)
            s(f"silo{n}.tolerance", 2.0)
            s(f"silo{n}.vib_mode", 2)
        s("water.tolerance", 2.0)
        s("water.head_overlap", 80)
        s("adx.count", 6)
        for n in ADX:
            s(f"adx{n}.used", n <= 6)
            s(f"adx{n}.tolerance", 3.0)
        s("batch.serial", 2417)
        s("batch.model", 3)
        s("batch.registered", True)
        s("batch.quantity", 1.0)
        s("plant.estop_healthy", True)
        s("plant.estop_ok", True)
        s("plant.air_pressure_ok", True)
        s("plant.ready", True)

    # --- simulation step ---
    def step(self, dt: float):
        for k in self.mem:
            self.server.lock_area(_srv_area(k[0]), k[1])
        try:
            self._step(dt)
        finally:
            for k in self.mem:
                self.server.unlock_area(_srv_area(k[0]), k[1])

    def _step(self, dt):
        g, s = self.get, self.set
        self.t += dt
        stage = g("batch.stage")

        # Refill bins and silos when the simulator refill bit is set (network 7).
        if g("plant.sim_refill"):
            for n in BINS:
                s(f"bin{n}.current", BIN_FULL)
            for n in SILOS:
                s(f"silo{n}.current", SILO_FULL)
            s("plant.sim_refill", False)

        self._alarms()
        ready = (g("plant.estop_healthy") and not g("batch.lockout") and not any(
            g(f"alarm.{a}") for a in ("0_0", "0_1", "0_5", "0_6", "1_2", "1_3", "1_7", "2_0", "2_4", "2_5")))
        s("plant.ready", ready or g("plant.test_mode"))

        if g("batch.abort"):
            self._end(aborted=True)
            return

        if g("batch.resume"):
            s("batch.pause", False)
            s("batch.pause_oot", False)
            s("batch.resume", False)
            self.fault_bin = None

        if stage == 0:
            self.idle_t += dt
            if self.auto_every and self.idle_t >= self.auto_every and g("plant.ready"):
                s("batch.quantity", self.rng.choice([0.5, 1.0, 1.5, 2.0, 3.0]))
                s("batch.run", True)
            if g("batch.run") and g("plant.ready"):
                self._begin()
            elif g("batch.run") and not g("plant.ready"):
                s("batch.run", False)  # the PLC will not start when not ready
            self._outputs(stage=0, paused=False)
            return

        paused = g("batch.pause") or g("batch.pause_oot")
        # In auto (demo) mode, act like an operator who resumes an out-of-tolerance pause after 30 s.
        self.paused_t = self.paused_t + dt if g("batch.pause_oot") else 0.0
        if self.auto_every and self.paused_t >= 30.0:
            s("batch.resume", True)
        if not g("plant.estop_healthy"):
            s("batch.pause", True)
            s("batch.estop_popup", True)
            paused = True
        if paused:
            self._outputs(stage, paused=True)
            return
        s("batch.estop_popup", False)
        self.stage_t += dt

        if stage == 1:
            s("batch.klaxon", self.stage_t < 4.0 and int(self.stage_t / 1.0) % 2 == 0)
            if self.stage_t >= 4.0:
                s("batch.klaxon", False)
                self._stage(2)
        elif stage == 2:
            done = self._batching(dt)
            if done:
                self._stage(3)
        elif stage == 3:
            self._discharge_admix(dt)
            if self.stage_t >= 10.0:
                self._end(aborted=False)
                return
        self._outputs(g("batch.stage"), paused=False)

    def _stage(self, n):
        self.set("batch.stage", n)
        self.stage_t = 0.0

    def _begin(self):
        g, s = self.get, self.set
        q = max(0.1, g("batch.quantity"))
        third = not g("plant.third_bin_na")
        for n in BINS:
            req = MIX[f"bin{n}"] * q if (n < 3 or third) else 0.0
            cur = g(f"bin{n}.current")
            s(f"bin{n}.required", req)
            s(f"bin{n}.start", cur)
            s(f"bin{n}.target", cur - req)
            s(f"bin{n}.batched", 0)
            s(f"bin{n}.pct", 0)
            s(f"bin{n}.not_used", req == 0)
            for f in ("complete", "precomplete", "over_tol", "under_tol"):
                s(f"bin{n}.{f}", False)
        for n in SILOS:
            req = MIX[f"silo{n}"] * q
            cur = g(f"silo{n}.current")
            s(f"silo{n}.required", req)
            s(f"silo{n}.start", cur)
            s(f"silo{n}.target", cur - req)
            s(f"silo{n}.batched", 0)
            s(f"silo{n}.pct", 0)
            for f in ("complete", "precomplete", "over_tol", "under_tol"):
                s(f"silo{n}.{f}", False)
        s("water.required", MIX["water"] * q)
        for f in ("head_level", "tail_level", "trimmed"):
            s(f"water.{f}", 0)
        s("water.tail_qty", MIX["water"] * q * 0.2)
        for f in ("head_complete", "head_precomplete", "tail_complete", "over_tol", "under_tol"):
            s(f"water.{f}", False)
        for n in ADX:
            req = MIX.get(f"adx{n}", 0.0) * q if g(f"adx{n}.used") else 0.0
            s(f"adx{n}.required", req)
            s(f"adx{n}.total_req", req)
            s(f"adx{n}.level", 0)
            s(f"adx{n}.filled", False)
            s(f"adx{n}.complete", req == 0)
        self.fault_bin = self.rng.choice(list(BINS)) if self.faults and self.rng.random() < 0.25 else None
        self.idle_t = 0.0
        self._stage(1)

    def _batching(self, dt) -> bool:
        g, s = self.get, self.set
        all_done = True
        for kind, items, rate in (("bin", BINS, GATE_RATE), ("silo", SILOS, AUGER_RATE)):
            for n in items:
                p = f"{kind}{n}"
                req = g(f"{p}.required")
                if req <= 0 or g(f"{p}.complete"):
                    s(f"{p}.run", False)
                    continue
                all_done = False
                batched = g(f"{p}.start") - g(f"{p}.current")
                if batched < req - FREE_FALL[kind]:
                    s(f"{p}.run", True)
                    flow = rate * (0.85 + 0.3 * self.rng.random())
                    flow = min(flow, g(f"{p}.current") / max(dt, 1e-3))
                    s(f"{p}.current", g(f"{p}.current") - flow * dt)
                    if kind == "bin":
                        s(f"{p}.flow", flow)
                else:
                    # Gate closed: material in flight lands, then the weight settles.
                    s(f"{p}.run", False)
                    s(f"{p}.precomplete", True)
                    if kind == "bin":
                        s(f"{p}.flow", 0.0)
                    err = self.rng.gauss(0, 0.004) * req
                    if kind == "bin" and self.fault_bin == n:
                        err = req * 0.045  # inject an over-tolerance result
                        self.fault_bin = None
                    s(f"{p}.current", g(f"{p}.start") - req - err)
                    batched = req + err
                    acc = err / req * 100
                    s(f"{p}.accuracy", acc)
                    s(f"{p}.accuracy_post", acc)
                    s(f"{p}.complete", True)
                    over, under = acc > g(f"{p}.tolerance"), acc < -g(f"{p}.tolerance")
                    s(f"{p}.over_tol", over)
                    s(f"{p}.under_tol", under)
                    if over or under:
                        s("batch.pause_oot", True)
                s(f"{p}.batched", batched)
                s(f"{p}.pct", min(100, int(batched / req * 100)))

        # Water: head water first, tail water after the aggregates are complete.
        req = g("water.required")
        head_req, tail_req = req - g("water.tail_qty"), g("water.tail_qty")
        head = g("water.head_level")
        if head < head_req:
            s("water.head_running", True)
            head = min(head_req, head + WATER_RATE * dt)
            s("water.head_level", head)
            all_done = False
        else:
            s("water.head_running", False)
            s("water.head_complete", True)
            s("water.head_precomplete", True)
            aggs_done = all(g(f"bin{n}.complete") or g(f"bin{n}.required") <= 0 for n in BINS)
            tail = g("water.tail_level")
            if aggs_done and tail < tail_req:
                s("water.tail_running", True)
                s("water.tail_level", min(tail_req, tail + WATER_RATE * dt))
                all_done = False
            elif tail >= tail_req:
                s("water.tail_running", False)
                if not g("water.tail_complete"):
                    s("water.tail_complete", True)
                    total = head + tail
                    s("water.accuracy", (total - req) / req * 100)
                    s("water.accuracy_post", (total - req) / req * 100)
                    s("water.meter_read", g("water.meter_read") + total)
                    s("water.total", int(total))
            else:
                all_done = False

        # Admix: fill each metering tank to its required amount.
        for n in ADX:
            req = g(f"adx{n}.required")
            if req <= 0:
                continue
            lvl = g(f"adx{n}.level")
            if lvl < req:
                s(f"adx{n}.level", min(req, lvl + ADX_RATE * dt))
                all_done = False
            elif not g(f"adx{n}.filled"):
                s(f"adx{n}.filled", True)
                err = self.rng.gauss(0, 0.01) * 100
                s(f"adx{n}.accuracy", err)
                s(f"adx{n}.accuracy_post", err)
        return all_done and not g("batch.pause_oot")

    def _discharge_admix(self, dt):
        for n in ADX:
            if self.get(f"adx{n}.filled"):
                self.set(f"adx{n}.complete", True)

    def _end(self, aborted: bool):
        g, s = self.get, self.set
        s("batch.run", False)
        s("batch.pause", False)
        s("batch.pause_oot", False)
        s("batch.abort", False)
        s("batch.klaxon", False)
        for n in BINS:
            s(f"bin{n}.run", False)
            s(f"bin{n}.flow", 0)
        for n in SILOS:
            s(f"silo{n}.run", False)
        s("water.head_running", False)
        s("water.tail_running", False)
        self._stage(0)
        self.idle_t = 0.0
        self._outputs(0, paused=False)

    def _alarms(self):
        g, s = self.get, self.set
        for n, (ff, empty) in {1: ("0_0", "0_1"), 2: ("0_5", "0_6"), 3: ("1_2", "1_3")}.items():
            s(f"alarm.{empty}", g(f"bin{n}.current") < 1500)
        for n, empty in {1: "2_0", 2: "2_5"}.items():
            s(f"alarm.{empty}", g(f"silo{n}.current") < 800)
        s("alarm.6_7", not g("plant.estop_healthy"))
        s("alarm.7_0", not g("plant.air_pressure_ok"))
        s("alarm.7_1", g("plant.ol3"))
        if self.faults:
            # A short air-pressure dip roughly every 15 minutes.
            phase = self.t % 900.0
            s("plant.air_pressure_ok", not (300.0 <= phase < 312.0))

    def _outputs(self, stage, paused):
        g, s = self.get, self.set
        active = stage in (2, 3) and not paused
        s("out.horn", g("batch.klaxon"))
        s("out.main_conv", active)
        s("plant.main_conv_running", active)
        s("out.air_comp", stage != 0 and g("plant.air_pressure_ok"))
        s("out.hyd_pump", g("plant.ready"))
        s("out.dust1", stage != 0)
        s("out.water_pump", (g("water.head_running") or g("water.tail_running")) and not paused)
        for n in BINS:
            run = g(f"bin{n}.run") and not paused
            s(f"out.agg{n}_open", run)
            s(f"out.agg{n}_close", not run and stage == 2)
            s(f"out.agg{n}_vib", run and int(self.t) % 4 == 0)
        s("out.agg3_belt", g("bin3.run") and not paused)
        for n in SILOS:
            run = g(f"silo{n}.run") and not paused
            s(f"out.auger{n}", run)
            s(f"out.silo{n}_aer", run)
            s(f"out.silo{n}_vib", run and int(self.t) % 5 == 0)
        for n in ADX:
            filling = stage == 2 and not paused and g(f"adx{n}.required") > 0 and not g(f"adx{n}.filled")
            s(f"out.adx{n}_fill", filling)
            s(f"out.adx{n}_dis", stage == 3 and not paused and g(f"adx{n}.filled") and self.stage_t < 3.0)


def _srv_area(area: str):
    return {"DB": SrvArea.DB, "Q": SrvArea.PA, "I": SrvArea.PE, "M": SrvArea.MK}[area]
