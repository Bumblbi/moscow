from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelematicsPoint(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=50)
    route_id: int = Field(gt=0)
    trip_id: str | None = Field(default=None, max_length=50)
    timestamp: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed: float = Field(ge=0, le=250)
    heading: float | None = Field(default=None, ge=0, lt=360)
    nearest_stop_id: int | None = Field(default=None, gt=0)
    door_status: str | None = Field(default=None, max_length=20)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class TelematicsBatch(BaseModel):
    points: list[TelematicsPoint] = Field(min_length=1, max_length=1000)


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    predicted_at: datetime
    horizon_min: int
    probability: float
    predicted_delay_min: float
    risk_level: str
    reason: str | None
    model_version: str
    latency_ms: float


class VehicleOut(BaseModel):
    vehicle_id: str
    route_id: int
    route_number: str
    trip_id: str | None
    lat: float | None
    lon: float | None
    speed: float | None
    current_delay_min: float
    probability: float | None
    predicted_delay_min: float | None
    risk_level: str | None
    reason: str | None
    updated_at: datetime


class IngestResult(BaseModel):
    vehicle: VehicleOut
    prediction: PredictionOut


class MLPredictionRequest(BaseModel):
    current_delay_min: float
    speed: float
    distance_to_stop_km: float
    hour: int = Field(ge=0, le=23)
    historical_delay_min: float
    dwell_seconds: float = 0.0
    horizon_min: int = Field(ge=10, le=15)


class MLPredictionResponse(BaseModel):
    probability: float = Field(ge=0, le=1)
    predicted_delay_min: float = Field(ge=0)
    reason: str
    model_version: str
