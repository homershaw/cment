"""Tag map for the concrete batch plant S7-1500 (CPU 1511-1 PN, program "Cment").

Every address below is taken from the TIA Portal program listing
(cment.pdf, OB1 "Main", networks 1-60). The listing shows the
absolute address of each DB member (e.g. %DB9.DBD14), which means these DBs use
standard (non-optimized) access and can be read with S7 PUT/GET.

The listing shows the access width (X = bit, W = word, D = double word) but not
always the data type. Assumptions, to be confirmed against the PLC:
  - DBD values are REAL (weights, levels, quantities, accuracy, flow).
  - DBW values are INT.
"""
from dataclasses import dataclass, field
from typing import Optional

SIZES = {"bool": 1, "int": 2, "word": 2, "real": 4, "dint": 4}


@dataclass(frozen=True)
class Tag:
    key: str            # stable id, e.g. "bin1.current"
    label: str
    area: str           # "DB", "Q", "I", "M"
    db: int             # DB number (0 for Q/I/M)
    byte: int
    bit: Optional[int] = None
    type: str = "real"  # bool, int, word, real, dint
    unit: str = ""
    group: str = ""
    trend: bool = False  # stored in the history database
    decimals: int = 1

    @property
    def size(self) -> int:
        return SIZES[self.type]

    @property
    def address(self) -> str:
        if self.area == "DB":
            if self.type == "bool":
                return f"DB{self.db}.DBX{self.byte}.{self.bit}"
            width = {2: "W", 4: "D"}[self.size]
            return f"DB{self.db}.DB{width}{self.byte}"
        if self.type == "bool":
            return f"{self.area}{self.byte}.{self.bit}"
        width = {2: "W", 4: "D"}[self.size]
        return f"{self.area}{width}{self.byte}"


TAGS: list[Tag] = []


def _add(*args, **kw) -> Tag:
    t = Tag(*args, **kw)
    TAGS.append(t)
    return t


def _bit(key, label, area, db, byte, bit, group, **kw):
    return _add(key, label, area, db, byte, bit, type="bool", group=group, decimals=0, **kw)


# --- Aggregate bins: Bin_1_Data DB9, Bin_2_Data DB14, Bin_3_Data DB17 (networks 35-37) ---
BINS = {1: 9, 2: 14, 3: 17}
for n, db in BINS.items():
    g, p = f"Agg {n}", f"bin{n}"
    _bit(f"{p}.run", "Running", "DB", db, 0, 0, g)
    _bit(f"{p}.not_used", "Not used", "DB", db, 0, 2, g)
    _bit(f"{p}.over_tol", "Over tolerance", "DB", db, 0, 3, g)
    _bit(f"{p}.under_tol", "Under tolerance", "DB", db, 0, 4, g)
    _add(f"{p}.start", "Start weight", "DB", db, 6, unit="kg", group=g, decimals=0)
    _add(f"{p}.target", "Target weight", "DB", db, 10, unit="kg", group=g, decimals=0)
    _add(f"{p}.current", "Weight", "DB", db, 14, unit="kg", group=g, trend=True, decimals=0)
    _add(f"{p}.batched", "Batched", "DB", db, 18, unit="kg", group=g, trend=True, decimals=0)
    _add(f"{p}.overlap", "Overlap", "DB", db, 22, type="int", unit="%", group=g, decimals=0)
    _bit(f"{p}.complete", "Complete", "DB", db, 24, 0, g)
    _bit(f"{p}.precomplete", "Pre-complete", "DB", db, 24, 1, g)
    _bit(f"{p}.no_flow", "No flow detected", "DB", db, 24, 2, g)
    _add(f"{p}.pct", "Complete", "DB", db, 26, type="int", unit="%", group=g, decimals=0)
    _add(f"{p}.vib_mode", "Vibrator mode", "DB", db, 36, type="int", group=g, decimals=0)
    _add(f"{p}.gate_mode", "Clam gate mode", "DB", db, 38, type="int", group=g, decimals=0)
    _add(f"{p}.required", "Required (moisture adj.)", "DB", db, 184, unit="kg", group=g, decimals=0)
    _add(f"{p}.step", "Sequence step", "DB", db, 208, type="int", group=g, decimals=0)
    _add(f"{p}.flow", "Flow rate", "DB", db, 210, unit="kg/s", group=g, trend=True)
    _add(f"{p}.accuracy", "Accuracy", "DB", db, 214, unit="%", group=g)
    _add(f"{p}.tolerance", "Tolerance", "DB", db, 218, unit="%", group=g)
    _add(f"{p}.accuracy_post", "Accuracy after complete", "DB", db, 222, unit="%", group=g)

# --- Cement silos: Silo_1_Data DB18, Silo_2_Data DB16 (networks 39-40) ---
SILOS = {1: 18, 2: 16}
for n, db in SILOS.items():
    g, p = f"Silo {n}", f"silo{n}"
    _bit(f"{p}.run", "Running", "DB", db, 0, 0, g)
    _bit(f"{p}.not_used", "Not used", "DB", db, 0, 2, g)
    _bit(f"{p}.over_tol", "Over tolerance", "DB", db, 0, 3, g)
    _bit(f"{p}.under_tol", "Under tolerance", "DB", db, 0, 4, g)
    _add(f"{p}.start", "Start weight", "DB", db, 2, unit="kg", group=g, decimals=0)
    _add(f"{p}.target", "Target weight", "DB", db, 6, unit="kg", group=g, decimals=0)
    _add(f"{p}.current", "Weight", "DB", db, 10, unit="kg", group=g, trend=True, decimals=0)
    _add(f"{p}.batched", "Batched", "DB", db, 14, unit="kg", group=g, trend=True, decimals=0)
    _bit(f"{p}.complete", "Complete", "DB", db, 18, 0, g)
    _bit(f"{p}.precomplete", "Pre-complete", "DB", db, 18, 1, g)
    _bit(f"{p}.no_flow", "No flow detected", "DB", db, 18, 2, g)
    _add(f"{p}.pct", "Complete", "DB", db, 20, type="int", unit="%", group=g, decimals=0)
    _add(f"{p}.vib_mode", "Vibrator mode", "DB", db, 42, type="int", group=g, decimals=0)
    _add(f"{p}.overlap", "Overlap", "DB", db, 44, type="int", unit="%", group=g, decimals=0)
    _add(f"{p}.required", "Required", "DB", db, 130, unit="kg", group=g, decimals=0)
    _add(f"{p}.step", "Sequence step", "DB", db, 138, type="int", group=g, decimals=0)
    _add(f"{p}.accuracy", "Accuracy", "DB", db, 144, unit="%", group=g)
    _add(f"{p}.tolerance", "Tolerance", "DB", db, 148, unit="%", group=g)
    _add(f"{p}.accuracy_post", "Accuracy after complete", "DB", db, 152, unit="%", group=g)

# --- Water: "Water Meter Data" DB12 (network 27), "Volume_Data" DB10 ---
g = "Water"
_add("water.required", "Required", "DB", 10, 82, unit="L", group=g)
_add("water.head_overlap", "Head water overlap", "DB", 12, 4, type="int", unit="%", group=g, decimals=0)
_add("water.head_level", "Head water", "DB", 12, 6, unit="L", group=g, trend=True)
_bit("water.head_running", "Head water running", "DB", 12, 10, 0, g)
_bit("water.head_complete", "Head water complete", "DB", 12, 10, 1, g)
_bit("water.head_precomplete", "Head water pre-complete", "DB", 12, 10, 2, g)
_bit("water.over_tol", "Over tolerance", "DB", 12, 10, 3, g)
_bit("water.under_tol", "Under tolerance", "DB", 12, 10, 4, g)
_bit("water.skip_tail", "Skip tail water", "DB", 12, 10, 5, g)
_add("water.tail_qty", "Tail water quantity", "DB", 12, 12, unit="L", group=g)
_add("water.tail_level", "Tail water", "DB", 12, 18, unit="L", group=g, trend=True)
_bit("water.tail_running", "Tail water running", "DB", 12, 22, 0, g)
_bit("water.tail_complete", "Tail water complete", "DB", 12, 22, 1, g)
_add("water.total", "Total water", "DB", 12, 24, type="int", unit="L", group=g, decimals=0)
_add("water.meter_read", "Meter reading", "DB", 12, 28, unit="L", group=g)
_bit("water.run_pump", "Pump request", "DB", 12, 32, 1, g)
_bit("water.no_flow", "No flow detected", "DB", 12, 52, 0, g)
_add("water.trimmed", "Quantity trimmed", "DB", 12, 58, unit="L", group=g)
_add("water.manual_added", "Manually added", "DB", 12, 62, unit="L", group=g)
_add("water.accuracy", "Accuracy", "DB", 12, 66, unit="%", group=g)
_add("water.tolerance", "Tolerance", "DB", 12, 70, unit="%", group=g)
_add("water.accuracy_post", "Accuracy after complete", "DB", 12, 74, unit="%", group=g)

# --- Admix units: ADX_Data DB31 (networks 21, 43-50). Units 7 and 8 sit higher in the DB. ---
ADX = {
    #   qty_req level complete total_req filled    over      under     acc  tol  post
    1: (4, 8, 12, 138, (162, 0), (162, 6), (162, 7), 166, 170, 174),
    2: (14, 18, 22, 142, (162, 1), (163, 0), (163, 1), 178, 182, 186),
    3: (24, 28, 32, 146, (162, 2), (163, 2), (163, 3), 190, 194, 198),
    4: (34, 38, 42, 150, (162, 3), (163, 4), (163, 5), 202, 206, 210),
    5: (44, 48, 52, 154, (162, 4), (163, 6), (163, 7), 214, 218, 222),
    6: (54, 58, 62, 158, (162, 5), (164, 0), (164, 1), 226, 230, 234),
    7: (238, 242, 246, 260, (264, 0), (264, 1), (264, 2), 266, 270, 274),
    8: (278, 282, 286, 300, (304, 0), (304, 1), (304, 2), 306, 310, 314),
}
_add("adx.count", "Admix units fitted", "DB", 31, 2, type="int", group="Admix", decimals=0)
for n, (qty, level, comp, total, filled, over, under, acc, tol, post) in ADX.items():
    g, p = f"Admix {n}", f"adx{n}"
    _bit(f"{p}.used", "In use", "DB", 31, 0, n - 1, g)
    _add(f"{p}.required", "Required", "DB", 31, qty, unit="L", group=g, decimals=2)
    _add(f"{p}.level", "Metered", "DB", 31, level, unit="L", group=g, trend=True, decimals=2)
    _bit(f"{p}.complete", "Complete", "DB", 31, comp, 1, g)
    _add(f"{p}.total_req", "Total required", "DB", 31, total, unit="L", group=g, decimals=2)
    _bit(f"{p}.filled", "Filled (ready)", "DB", 31, filled[0], filled[1], g)
    _bit(f"{p}.over_tol", "Over tolerance", "DB", 31, over[0], over[1], g)
    _bit(f"{p}.under_tol", "Under tolerance", "DB", 31, under[0], under[1], g)
    _add(f"{p}.accuracy", "Accuracy", "DB", 31, acc, unit="%", group=g)
    _add(f"{p}.tolerance", "Tolerance", "DB", 31, tol, unit="%", group=g)
    _add(f"{p}.accuracy_post", "Accuracy after complete", "DB", 31, post, unit="%", group=g)

# --- Batch control: "Assorted_control_data" DB30 ---
g = "Batch"
_add("batch.serial", "Serial number", "DB", 30, 0, type="int", group=g, decimals=0)
_add("batch.model", "Model number", "DB", 30, 8, type="int", group=g, decimals=0)
_bit("batch.complete_pulse", "Batch complete pulse", "DB", 30, 10, 1, g)
_bit("batch.estop_popup", "E-stop hit mid batch", "DB", 30, 10, 3, g)
_bit("batch.abort", "Abort", "DB", 30, 10, 4, g)
_bit("batch.resume", "Resume", "DB", 30, 10, 6, g)
_bit("batch.pause_oot", "Paused: out of tolerance", "DB", 30, 10, 7, g)
_add("batch.stage", "Process stage", "DB", 30, 14, type="int", group=g, decimals=0)
_bit("batch.klaxon", "Klaxon sounding", "DB", 30, 16, 1, g)
_bit("batch.learned_ff", "Learned free fall", "DB", 30, 16, 3, g)
_bit("batch.run", "Run batch", "DB", 30, 16, 4, g)
_bit("batch.pause", "Pause batch", "DB", 30, 16, 5, g)
_bit("batch.registered", "Registered", "DB", 30, 16, 7, g)
_bit("batch.lockout", "Registration lockout", "DB", 30, 17, 0, g)
_add("batch.quantity", "Batch quantity", "DB", 30, 20, unit="m³", group=g, decimals=2)

# --- Plant status flags (M memory) and manual mode ---
g = "Plant"
_bit("plant.ready", "Ready to run", "M", 0, 0, 0, g)
_bit("plant.main_conv_running", "Main conveyor running", "M", 0, 0, 5, g)
_bit("plant.third_bin_na", "Third bin not available", "M", 0, 1, 2, g)
_bit("plant.test_mode", "Manual (test) mode", "DB", 15, 0, 0, g)
# The program uses "Simulator".Estop (DB63.DBX0.0) as its e-stop signal: TRUE = healthy.
# Ready To Run needs it TRUE and "Estop fault" is raised when it is FALSE (networks 5, 23, 24).
_bit("plant.estop_healthy", "E-stop circuit healthy (DB63)", "DB", 63, 0, 0, g)
_bit("plant.sim_refill", "Simulator refill", "DB", 63, 0, 1, g)
_bit("plant.estop_ok", "E-stop OK", "I", 0, 4, 7, g)
_bit("plant.air_pressure_ok", "Air pressure switch", "I", 0, 4, 6, g)
_bit("plant.ol3", "Main conveyor overload OL3", "I", 0, 0, 2, g)

# --- Outputs (Q). Addresses from the program; the panel drawings number the same
#     points by card slot and channel. ---
OUTPUTS = [
    ("air_comp", "Air compressor", 0, 0), ("water_pump", "Water pump", 0, 1),
    ("hyd_pump", "Hydraulic pump", 0, 2), ("silo1_vib", "Silo 1 vibrator", 0, 3),
    ("silo2_vib", "Silo 2 vibrator", 0, 4), ("agg1_vib", "Agg 1 vibrator", 0, 5),
    ("agg2_vib", "Agg 2 vibrator", 0, 6), ("agg3_vib", "Agg 3 vibrator", 0, 7),
    ("main_conv", "Main conveyor", 1, 0), ("horn", "Horn", 1, 1),
    ("dust1", "Dust collector 1", 1, 2), ("dust2", "Dust collector 2", 1, 3),
    ("silo1_aer", "Silo 1 aerator", 1, 4), ("silo2_aer", "Silo 2 aerator", 1, 5),
    ("auger1", "Auger 1", 1, 6), ("auger2", "Auger 2", 1, 7),
    ("agg3_belt", "Agg 3 belt", 2, 0), ("agg1_open", "Agg 1 gate open", 2, 1),
    ("agg1_close", "Agg 1 gate close", 2, 2), ("agg2_open", "Agg 2 gate open", 2, 3),
    ("agg2_close", "Agg 2 gate close", 2, 4), ("agg3_open", "Agg 3 gate open", 2, 5),
    ("agg3_close", "Agg 3 gate close", 2, 6),
    ("adx1_fill", "Admix 1 fill", 2, 7), ("adx1_dis", "Admix 1 discharge", 3, 2),
    ("adx2_fill", "Admix 2 fill", 3, 3), ("adx2_dis", "Admix 2 discharge", 3, 4),
    ("adx3_fill", "Admix 3 fill", 3, 5), ("adx3_dis", "Admix 3 discharge", 3, 6),
    ("adx4_fill", "Admix 4 fill", 3, 7), ("adx4_dis", "Admix 4 discharge", 4, 0),
    ("adx5_fill", "Admix 5 fill", 4, 1), ("adx5_dis", "Admix 5 discharge", 4, 2),
    ("adx6_fill", "Admix 6 fill", 4, 3), ("adx6_dis", "Admix 6 discharge", 4, 4),
    ("adx7_fill", "Admix 7 fill", 4, 5), ("adx7_dis", "Admix 7 discharge", 4, 6),
    ("adx8_fill", "Admix 8 fill", 4, 7), ("adx8_dis", "Admix 8 discharge", 5, 0),
]
for key, label, byte, bit in OUTPUTS:
    _bit(f"out.{key}", label, "Q", 0, byte, bit, "Outputs")

# --- Alarms: Alarm_Data DB20 (networks 17-18, 23, 35-50) ---
ALARMS = [
    (0, 0, "Bin 1 free-flow fault"), (0, 1, "Bin 1 empty"), (0, 2, "Bin 1 large free-fall correction"),
    (0, 5, "Bin 2 free-flow fault"), (0, 6, "Bin 2 empty"), (0, 7, "Bin 2 large free-fall correction"),
    (1, 2, "Bin 3 free-flow fault"), (1, 3, "Bin 3 empty"), (1, 4, "Bin 3 large free-fall correction"),
    (1, 7, "Silo 1 free-flow fault"), (2, 0, "Silo 1 empty"), (2, 1, "Silo 1 large free-fall correction"),
    (2, 4, "Silo 2 free-flow fault"), (2, 5, "Silo 2 empty"), (2, 6, "Silo 2 large free-fall correction"),
    (3, 1, "Admix 1 fill fault"), (3, 2, "Admix 1 discharge fault"), (3, 3, "Admix 1 full at start"),
    (3, 6, "Admix 2 fill fault"), (3, 7, "Admix 2 discharge fault"), (4, 0, "Admix 2 full at start"),
    (4, 3, "Admix 3 fill fault"), (4, 4, "Admix 3 discharge fault"), (4, 5, "Admix 3 full at start"),
    (5, 0, "Admix 4 fill fault"), (5, 1, "Admix 4 discharge fault"), (5, 2, "Admix 4 full at start"),
    (5, 5, "Admix 5 fill fault"), (5, 6, "Admix 5 discharge fault"), (5, 7, "Admix 5 full at start"),
    (6, 2, "Admix 6 fill fault"), (6, 3, "Admix 6 discharge fault"), (6, 4, "Admix 6 full at start"),
    (6, 7, "E-stop fault"),
    (7, 0, "Air pressure fault"), (7, 1, "Main conveyor tripped"),
    (7, 3, "Admix 7 fill fault"), (7, 4, "Admix 7 discharge fault"), (7, 5, "Admix 7 full at start"),
    (8, 0, "Admix 8 fill fault"), (8, 1, "Admix 8 discharge fault"), (8, 2, "Admix 8 full at start"),
]
for byte, bit, text in ALARMS:
    _bit(f"alarm.{byte}_{bit}", text, "DB", 20, byte, bit, "Alarms")

BY_KEY: dict[str, Tag] = {t.key: t for t in TAGS}
ALARM_TAGS = [t for t in TAGS if t.group == "Alarms"]
TREND_TAGS = [t for t in TAGS if t.trend]

# Writable tags for batch control. Nothing else is ever written.
WRITABLE = {"batch.run", "batch.pause", "batch.resume", "batch.abort", "batch.quantity"}


def check_unique() -> None:
    """Raise if two tags overlap in PLC memory (catches typos in the tables above)."""
    seen: dict[tuple, str] = {}
    for t in TAGS:
        if t.type == "bool":
            cells = [(t.area, t.db, t.byte, t.bit)]
        else:
            cells = [(t.area, t.db, t.byte + i, b) for i in range(t.size) for b in range(8)]
        for c in cells:
            if c in seen:
                raise ValueError(f"{t.key} overlaps {seen[c]} at {c}")
            seen[c] = t.key
