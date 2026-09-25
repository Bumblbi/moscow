import json
import math
import time
from dataclasses import dataclass
from datetime import UTC

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import Prediction, Schedule, Vehicle
from .schemas import MLPredictionRequest, MLPredictionResponse, TelematicsPoint, VehicleOut


def risk_level(probability: float) -> str:
    if probability >= 0.7:
        return "high"
    if probability >= 0.4:
        return "medium"
    return "low"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def fallback_prediction(request: MLPredictionRequest) -> MLPredictionResponse:
    congestion = max(0.0, 20.0 - request.speed) / 20.0
    dwell = min(request.dwell_seconds / 180.0, 1.0)
    raw = -1.5 + 0.42 * request.current_delay_min + 1.25 * congestion + 0.55 * dwell
    probability = 1.0 / (1.0 + math.exp(-raw))
    delay = max(0.0, request.current_delay_min + congestion * 4.0 + dwell * 2.0)
    if dwell >= 0.5:
        reason = "длительная стоянка"
    elif request.speed < 12:
        reason = "аномально низкая скорость"
    elif request.current_delay_min >= 3:
        reason = "накопленное отклонение от графика"
    else:
        reason = "рисковый паттерн не выявлен"
    return MLPredictionResponse(
        probability=round(probability, 4),
        predicted_delay_min=round(delay, 2),
        reason=reason,
        model_version="fallback-v1",
    )


@dataclass
class PredictionResult:
    response: MLPredictionResponse
    latency_ms: float


class PredictionClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def predict(self, features: MLPredictionRequest) -> PredictionResult:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.settings.ml_timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.ml_service_url.rstrip('/')}/predict",
                    json=features.model_dump(),
                )
                response.raise_for_status()
                parsed = MLPredictionResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            parsed = fallback_prediction(features)
        return PredictionResult(parsed, (time.perf_counter() - started) * 1000)


class Cache:
    def __init__(self, url: str):
        self.client = Redis.from_url(url, decode_responses=True) if url else None

    async def set_vehicle(self, vehicle: VehicleOut) -> None:
        if not self.client:
            return
        try:
            await self.client.setex(f"vehicle:{vehicle.vehicle_id}", 120, json.dumps(vehicle.model_dump(mode="json")))
        except Exception:
            return

    async def ping(self) -> bool:
        if not self.client:
            return False
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()


async def calculate_delay(session: AsyncSession, point: TelematicsPoint) -> float:
    if not point.trip_id or not point.nearest_stop_id:
        return 0.0
    planned = await session.scalar(
        select(Schedule.planned_arrival).where(
            Schedule.route_id == point.route_id,
            Schedule.trip_id == point.trip_id,
            Schedule.stop_id == point.nearest_stop_id,
        )
    )
    if not planned:
        return 0.0
    if planned.tzinfo is None:
        planned = planned.replace(tzinfo=UTC)
    return round((point.timestamp - planned).total_seconds() / 60.0, 2)


async def historical_delay(session: AsyncSession, vehicle_id: str) -> float:
    value = await session.scalar(select(func.avg(Vehicle.current_delay_min)).where(Vehicle.id == vehicle_id))
    return float(value or 0.0)


async def latest_prediction(session: AsyncSession, vehicle_id: str) -> Prediction | None:
    return await session.scalar(
        select(Prediction).where(Prediction.vehicle_id == vehicle_id).order_by(Prediction.predicted_at.desc()).limit(1)
    )


def vehicle_output(vehicle: Vehicle, prediction: Prediction | None) -> VehicleOut:
    return VehicleOut(
        vehicle_id=vehicle.id,
        route_id=vehicle.route_id,
        route_number=vehicle.route.route_number,
        trip_id=vehicle.trip_id,
        lat=vehicle.last_lat,
        lon=vehicle.last_lon,
        speed=vehicle.last_speed,
        current_delay_min=vehicle.current_delay_min,
        probability=prediction.probability if prediction else None,
        predicted_delay_min=prediction.predicted_delay_min if prediction else None,
        risk_level=prediction.risk_level if prediction else None,
        reason=prediction.reason if prediction else None,
        updated_at=vehicle.updated_at,
    )


async def build_features(
    session: AsyncSession, point: TelematicsPoint, delay: float, horizon: int
) -> MLPredictionRequest:
    dwell = 180.0 if point.door_status == "open" and point.speed < 1 else 0.0
    return MLPredictionRequest(
        current_delay_min=delay,
        speed=point.speed,
        distance_to_stop_km=0.0,
        hour=point.timestamp.hour,
        historical_delay_min=await historical_delay(session, point.vehicle_id),
        dwell_seconds=dwell,
        horizon_min=horizon,
    )
