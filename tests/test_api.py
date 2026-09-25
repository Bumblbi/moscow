import os
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_transport.db"
os.environ["ML_TIMEOUT_SECONDS"] = "0.05"
os.environ["REDIS_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_health_and_end_to_end_ingest():
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["database"] is True

        routes = client.get("/api/v1/routes").json()["routes"]
        assert routes[0]["route_number"] == "М2"

        schedules = client.get("/api/v1/schedules", params={"route_id": 1}).json()["schedules"]
        payload = {
            "vehicle_id": "BUS-TEST",
            "route_id": 1,
            "trip_id": "M2-001",
            "timestamp": datetime.now(UTC).isoformat(),
            "lat": 55.7522,
            "lon": 37.6156,
            "speed": 8,
            "heading": 90,
            "nearest_stop_id": schedules[0]["stop_id"],
            "door_status": "closed",
        }
        response = client.post("/api/v1/telematics", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["vehicle"]["vehicle_id"] == "BUS-TEST"
        assert body["prediction"]["model_version"] == "fallback-v1"

        listed = client.get("/api/v1/vehicles", params={"risk_level": body["prediction"]["risk_level"]})
        assert listed.status_code == 200
        assert any(item["vehicle_id"] == "BUS-TEST" for item in listed.json()["vehicles"])
