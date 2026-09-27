from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime


NPL_HEADER = struct.Struct("<HHHHBIH")
NPH_HEADER = struct.Struct("<HHHI")
NAV_CELL = struct.Struct("<IIIBBHHHHHBB")
SIGNATURE = 0x7E7E
REALTIME_TYPE = 101


@dataclass(frozen=True)
class NdtpNavigation:
    unit_id: int
    timestamp: datetime
    lat: float
    lon: float
    speed: float
    heading: float
    location_valid: bool


def decode_frame(npl: bytes, payload: bytes) -> NdtpNavigation | None:
    """Decode the navigation cell from one complete NDTP frame."""
    signature, data_size, _flags, _crc, packet_type, unit_id, _request_id = NPL_HEADER.unpack(npl)
    if signature != SIGNATURE or packet_type != 2 or data_size != len(payload) or len(payload) < NPH_HEADER.size:
        return None
    _service_id, message_type, _nph_flags, _nph_request_id = NPH_HEADER.unpack_from(payload)
    if message_type != REALTIME_TYPE:
        return None
    cells = payload[NPH_HEADER.size :]
    if len(cells) < 2 + NAV_CELL.size or cells[0] != 0:
        return None
    (
        timestamp,
        longitude,
        latitude,
        extra,
        _battery,
        speed_avg,
        _speed_max,
        course,
        _track,
        _altitude,
        _satellites,
        _pdop,
    ) = NAV_CELL.unpack_from(cells, 2)
    lon = longitude / 10_000_000
    lat = latitude / 10_000_000
    if not extra & (1 << 6):
        lon = -lon
    if not extra & (1 << 5):
        lat = -lat
    return NdtpNavigation(
        unit_id=unit_id,
        timestamp=datetime.fromtimestamp(timestamp, UTC),
        lat=lat,
        lon=lon,
        speed=float(speed_avg),
        heading=float(course),
        location_valid=bool(extra & (1 << 7)),
    )
