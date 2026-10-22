"""snap7 server with correct single-bit writes.

python-snap7's server writes a bit request as a whole byte (losing the bit number),
which would clear neighbouring bits. A real S7-1500 writes only the addressed bit,
so this subclass does the same.
"""
import struct
import threading

import snap7
from snap7.datatypes import S7WordLen

_local = threading.local()


class PlcServer(snap7.server.Server):
    def _parse_address_specification(self, addr_spec: bytes):
        spec = super()._parse_address_specification(addr_spec)
        if spec and spec.get("word_len") == S7WordLen.BIT:
            spec["bit"] = struct.unpack(">I", b"\x00" + bytes(addr_spec[9:12]))[0] % 8
        return spec

    def _handle_write_area(self, request, client_address):
        spec = request.get("parameters", {}).get("address_spec", {})
        _local.bit = spec.get("bit") if spec.get("word_len") == S7WordLen.BIT else None
        try:
            return super()._handle_write_area(request, client_address)
        finally:
            _local.bit = None

    def _write_to_memory_area(self, area, db_number, start, write_data):
        bit = getattr(_local, "bit", None)
        if bit is None:
            return super()._write_to_memory_area(area, db_number, start, write_data)
        key = (area, db_number)
        if key not in self.memory_areas or start >= len(self.memory_areas[key]):
            return False
        with self.area_locks[key]:
            mem = self.memory_areas[key]
            if write_data[0] & 1:
                mem[start] |= 1 << bit
            else:
                mem[start] &= ~(1 << bit) & 0xFF
        return True
