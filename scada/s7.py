"""S7 communication: read the tag map in a few block reads, decode values, write batch commands.

The PLC is read with S7 PUT/GET (snap7). Each DB (and the Q, I and M areas) is read
as one contiguous block covering every tag in it, then decoded locally, so a poll
is about 15 requests regardless of the tag count.
"""
import logging
import struct
import threading
from dataclasses import dataclass
from typing import Optional

import snap7
from snap7.type import Area, WordLen

from .tags import BY_KEY, TAGS, WRITABLE, Tag

log = logging.getLogger(__name__)

AREAS = {"DB": Area.DB, "Q": Area.PA, "I": Area.PE, "M": Area.MK}
MAX_CHUNK = 400  # bytes per read; below the smallest S7-1500 PDU payload


@dataclass
class Block:
    area: str
    db: int
    start: int
    size: int
    tags: list


def plan_blocks(tags: list[Tag]) -> list[Block]:
    groups: dict[tuple, list[Tag]] = {}
    for t in tags:
        groups.setdefault((t.area, t.db), []).append(t)
    blocks = []
    for (area, db), ts in sorted(groups.items()):
        start = min(t.byte for t in ts)
        end = max(t.byte + t.size for t in ts)
        blocks.append(Block(area, db, start, end - start, ts))
    return blocks


def decode(tag: Tag, data: bytes, base: int):
    off = tag.byte - base
    if tag.type == "bool":
        return bool(data[off] >> tag.bit & 1)
    if tag.type == "int":
        return struct.unpack_from(">h", data, off)[0]
    if tag.type == "word":
        return struct.unpack_from(">H", data, off)[0]
    if tag.type == "dint":
        return struct.unpack_from(">i", data, off)[0]
    v = struct.unpack_from(">f", data, off)[0]
    return None if v != v or abs(v) == float("inf") else v  # NaN/inf -> no value


def encode(tag: Tag, value) -> bytes:
    if tag.type == "int":
        return struct.pack(">h", int(value))
    if tag.type == "word":
        return struct.pack(">H", int(value))
    if tag.type == "dint":
        return struct.pack(">i", int(value))
    if tag.type == "real":
        return struct.pack(">f", float(value))
    raise ValueError(f"cannot encode {tag.type}")


class PlcError(Exception):
    pass


class S7Link:
    """One snap7 client, reconnecting on demand. All calls are serialized with a lock."""

    def __init__(self, host: str, rack: int = 0, slot: int = 1, port: int = 102):
        self.host, self.rack, self.slot, self.port = host, rack, slot, port
        self.client = snap7.client.Client()
        self.lock = threading.Lock()
        self.blocks = plan_blocks(TAGS)
        self.last_error: Optional[str] = None

    def _ensure(self):
        if not self.client.get_connected():
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = snap7.client.Client()
            self.client.connect(self.host, self.rack, self.slot, self.port)

    def _read(self, area: str, db: int, start: int, size: int) -> bytearray:
        out = bytearray()
        while size > 0:
            n = min(size, MAX_CHUNK)
            out += self.client.read_area(AREAS[area], db, start, n)
            start, size = start + n, size - n
        return out

    def read_all(self) -> dict:
        """Read every tag. Raises PlcError (and drops the connection) on any failure."""
        with self.lock:
            try:
                self._ensure()
                values = {}
                for b in self.blocks:
                    data = self._read(b.area, b.db, b.start, b.size)
                    for t in b.tags:
                        values[t.key] = decode(t, data, b.start)
                self.last_error = None
                return values
            except Exception as e:
                self._drop(e)
                raise PlcError(self.last_error) from e

    def write(self, key: str, value) -> None:
        """Write one batch-control tag. Only tags in WRITABLE can be written."""
        if key not in WRITABLE:
            raise PlcError(f"{key} is not writable")
        tag = BY_KEY[key]
        with self.lock:
            try:
                self._ensure()
                if tag.type == "bool":
                    # Single-bit write: the PLC changes only this bit, never its neighbours.
                    self.client.write_area(AREAS[tag.area], tag.db, tag.byte * 8 + tag.bit,
                                           bytearray([1 if value else 0]), WordLen.Bit)
                else:
                    self.client.write_area(AREAS[tag.area], tag.db, tag.byte, bytearray(encode(tag, value)))
            except Exception as e:
                self._drop(e)
                raise PlcError(self.last_error) from e

    def _drop(self, e: Exception):
        self.last_error = f"{type(e).__name__}: {e}"
        log.warning("PLC %s: %s", self.host, self.last_error)
        try:
            self.client.disconnect()
        except Exception:
            pass

    def close(self):
        with self.lock:
            try:
                self.client.disconnect()
            except Exception:
                pass
