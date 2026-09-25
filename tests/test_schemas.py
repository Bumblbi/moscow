from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import TelematicsBatch, TelematicsPoint


def point(**overrides):
    data = {
        "vehicle_id": "BUS-1",
        "route_id": 1,
        "trip_id": "T-1",
        "timestamp": datetime.now(UTC),
        "lat": 55.7,
        "lon": 37.6,
        "speed": 20,
        "heading": 90,
        "nearest_stop_id": 1,
    }
    data.update(overrides)
    return TelematicsPoint(**data)


def test_telematics_rejects_naive_timestamp():
    with pytest.raises(ValidationError):
        point(timestamp=datetime.now())


def test_telematics_rejects_invalid_coordinate():
    with pytest.raises(ValidationError):
        point(lat=100)


def test_batch_limit():
    with pytest.raises(ValidationError):
        TelematicsBatch(points=[point()] * 1001)
