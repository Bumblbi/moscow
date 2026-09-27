from datetime import UTC, datetime

from app.ndtp import NAV_CELL, NPH_HEADER, NPL_HEADER, decode_frame


def test_decode_realtime_navigation_cell():
    now = int(datetime.now(UTC).timestamp())
    nav = NAV_CELL.pack(
        now,
        376_173_210,
        557_551_234,
        (1 << 5) | (1 << 6) | (1 << 7),
        120,
        28,
        31,
        90,
        100,
        150,
        10,
        2,
    )
    payload = NPH_HEADER.pack(1, 101, 1, 2) + bytes((0, 0)) + nav
    npl = NPL_HEADER.pack(0x7E7E, len(payload), 0, 0, 2, 1166336, 0)

    result = decode_frame(npl, payload)

    assert result is not None
    assert result.unit_id == 1166336
    assert abs(result.lat - 55.7551234) < 1e-7
    assert abs(result.lon - 37.6173210) < 1e-7
    assert result.speed == 28
    assert result.heading == 90
    assert result.location_valid is True


def test_ignore_handshake_packet():
    payload = NPH_HEADER.pack(0, 100, 1, 1) + bytes(18)
    npl = NPL_HEADER.pack(0x7E7E, len(payload), 0, 0, 2, 1, 0)
    assert decode_frame(npl, payload) is None
