"""Batch control: start, pause, resume and abort. Every request is checked against live PLC
state first and recorded in the event log with the user and the outcome."""
import time

from .config import Config
from .engine import Engine
from .s7 import PlcError

MAX_AGE_S = 3.0  # refuse to act on PLC values older than this


class ControlError(Exception):
    pass


class Control:
    def __init__(self, cfg: Config, engine: Engine):
        self.cfg, self.engine = cfg, engine

    def _live(self) -> dict:
        """Fresh PLC values for the interlock checks. The poll snapshot can be up to one poll
        old, which would let a quick second Start through before the first one shows."""
        e = self.engine
        if not self.cfg.control_enabled:
            raise ControlError("Batch control is disabled in config.toml ([control] enabled = false)")
        if not e.connected or time.time() - e.ts > MAX_AGE_S:
            raise ControlError("No live PLC data")
        try:
            return e.link.read_all()
        except PlcError as err:
            raise ControlError(f"PLC read failed: {err}") from err

    def _write(self, user: str, action: str, detail: str, writes: list[tuple[str, object]]):
        try:
            for key, value in writes:
                self.engine.link.write(key, value)
        except PlcError as err:
            self.engine.store.event(f"control.{action}", f"{detail} FAILED: {err}", user, ok=False)
            raise ControlError(f"PLC write failed: {err}") from err
        self.engine.store.event(f"control.{action}", detail, user)

    def _refuse(self, user, action, reason):
        self.engine.store.event(f"control.{action}", f"refused: {reason}", user, ok=False)
        raise ControlError(reason)

    def start(self, user: str, quantity: float):
        v = self._live()
        if not (self.cfg.min_quantity <= quantity <= self.cfg.max_quantity):
            self._refuse(user, "start", f"quantity must be {self.cfg.min_quantity}-{self.cfg.max_quantity} m3")
        if v.get("batch.stage") != 0 or v.get("batch.run"):
            self._refuse(user, "start", "a batch is already running")
        if not v.get("plant.ready"):
            self._refuse(user, "start", "plant is not Ready To Run")
        if v.get("plant.test_mode"):
            self._refuse(user, "start", "plant is in manual (test) mode")
        if v.get("batch.lockout"):
            self._refuse(user, "start", "PLC registration lockout")
        # Write the quantity and read it back before setting Run_Batch.
        self._write(user, "quantity", f"{quantity:.2f} m3", [("batch.quantity", quantity)])
        back = self.engine.link.read_all().get("batch.quantity")
        if back is None or abs(back - quantity) > 0.005:
            self._refuse(user, "start", f"quantity read back {back}, expected {quantity}")
        self._write(user, "start", f"{quantity:.2f} m3", [("batch.run", True)])

    def pause(self, user: str):
        v = self._live()
        if v.get("batch.stage") == 0:
            self._refuse(user, "pause", "no batch is running")
        if v.get("batch.pause"):
            self._refuse(user, "pause", "batch is already paused")
        self._write(user, "pause", f"stage {v.get('batch.stage')}", [("batch.pause", True)])

    def resume(self, user: str):
        v = self._live()
        if not (v.get("batch.pause") or v.get("batch.pause_oot")):
            self._refuse(user, "resume", "batch is not paused")
        if not v.get("plant.estop_healthy"):
            self._refuse(user, "resume", "e-stop circuit is not healthy")
        why = "out of tolerance" if v.get("batch.pause_oot") else "operator pause"
        self._write(user, "resume", why, [("batch.resume", True), ("batch.pause", False)])

    def abort(self, user: str):
        v = self._live()
        if v.get("batch.stage") == 0:
            self._refuse(user, "abort", "no batch is running")
        self._write(user, "abort", f"stage {v.get('batch.stage')}", [("batch.abort", True)])
