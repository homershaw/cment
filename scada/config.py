import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    plc_host: str = "127.0.0.1"
    plc_rack: int = 0
    plc_slot: int = 1
    plc_port: int = 102
    poll_ms: int = 1000
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    db_path: Path = ROOT / "data" / "scada.db"
    sample_s: float = 5.0
    keep_days: int = 180
    control_enabled: bool = False
    min_quantity: float = 0.25
    max_quantity: float = 12.0
    stages: dict = field(default_factory=lambda: {0: "Idle"})


def load(path: Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "config.toml"
    if not path.exists():
        path = ROOT / "config.example.toml"
    d = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM (Notepad, PowerShell)
    plc, web, db = d.get("plc", {}), d.get("web", {}), d.get("database", {})
    hist, ctl = d.get("history", {}), d.get("control", {})
    db_path = Path(db.get("path", "data/scada.db"))
    return Config(
        plc_host=plc.get("host", "127.0.0.1"), plc_rack=plc.get("rack", 0), plc_slot=plc.get("slot", 1),
        plc_port=plc.get("port", 102), poll_ms=plc.get("poll_ms", 1000),
        web_host=web.get("host", "0.0.0.0"), web_port=web.get("port", 8080),
        db_path=db_path if db_path.is_absolute() else ROOT / db_path,
        sample_s=hist.get("sample_s", 5), keep_days=hist.get("keep_days", 180),
        control_enabled=ctl.get("enabled", False),
        min_quantity=ctl.get("min_quantity", 0.25), max_quantity=ctl.get("max_quantity", 12.0),
        stages={int(k): v for k, v in d.get("stages", {"0": "Idle"}).items()},
    )
