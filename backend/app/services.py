import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, timedelta
from statistics import pstdev

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import Prediction, Schedule, Stop, TelematicsHistory, Vehicle
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

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.settings.ml_timeout_seconds) as client:
                response = await client.get(f"{self.settings.ml_service_url.rstrip('/')}/health")
                response.raise_for_status()
                payload = response.json()
            return bool(payload.get("model_loaded"))
        except (httpx.HTTPError, ValueError):
            return False

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
    values = (
        await session.scalars(
            select(Prediction.predicted_delay_min)
            .where(Prediction.vehicle_id == vehicle_id)
            .order_by(Prediction.predicted_at.desc())
            .limit(20)
        )
    ).all()
    return float(sum(values) / len(values)) if values else 0.0


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
    def aware(value):
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    history = (
        await session.scalars(
            select(TelematicsHistory)
            .where(
                TelematicsHistory.vehicle_id == point.vehicle_id,
                TelematicsHistory.timestamp <= point.timestamp,
                TelematicsHistory.timestamp >= point.timestamp - timedelta(minutes=15),
            )
            .order_by(TelematicsHistory.timestamp)
        )
    ).all()
    target = (
        await session.execute(
            select(Schedule, Stop)
            .join(Stop, Stop.id == Schedule.stop_id)
            .where(
                Schedule.route_id == point.route_id,
                Schedule.trip_id == point.trip_id,
                Schedule.planned_arrival >= point.timestamp + timedelta(minutes=10),
                Schedule.planned_arrival <= point.timestamp + timedelta(minutes=15),
            )
            .order_by(Schedule.planned_arrival)
            .limit(1)
        )
    ).first()
    if target is None and point.nearest_stop_id:
        target = (
            await session.execute(
                select(Schedule, Stop)
                .join(Stop, Stop.id == Schedule.stop_id)
                .where(
                    Schedule.route_id == point.route_id,
                    Schedule.trip_id == point.trip_id,
                    Schedule.stop_id == point.nearest_stop_id,
                )
                .limit(1)
            )
        ).first()
    target_schedule, target_stop = target if target else (None, None)
    target_lat = target_stop.lat if target_stop else point.lat
    target_lon = target_stop.lon if target_stop else point.lon
    distance = haversine_km(point.lat, point.lon, target_lat, target_lon)
    dwell = 0.0
    for row in reversed(history):
        if row.speed >= 1 or row.door_status != "open":
            break
        dwell = max(0.0, (point.timestamp - aware(row.timestamp)).total_seconds())

    seconds_of_day = point.timestamp.hour * 3600 + point.timestamp.minute * 60 + point.timestamp.second
    phase = 2 * math.pi * seconds_of_day / 86400
    model_features: dict[str, float | None] = {
        "cur_dev_s": delay * 60,
        "horizon_s": (
            (target_schedule.planned_arrival.replace(tzinfo=UTC) - point.timestamp).total_seconds()
            if target_schedule and target_schedule.planned_arrival.tzinfo is None
            else (target_schedule.planned_arrival - point.timestamp).total_seconds()
            if target_schedule
            else horizon * 60
        ),
        "hour_sin": math.sin(phase),
        "hour_cos": math.cos(phase),
        "weekday": float(point.timestamp.weekday()),
        "target_lon": target_lon,
        "target_lat": target_lat,
        "manual_fill": 0.0,
        "last_lon": point.lon,
        "last_lat": point.lat,
        "last_speed": point.speed,
        "last_heading": point.heading,
        "telemetry_age_s": 0.0,
        "distance_to_target_km": distance,
        "cur_dev_mean_15m": delay * 60,
        "cur_dev_std_15m": 0.0,
    }
    if point.heading is not None and distance > 0:
        lat1, lat2 = math.radians(point.lat), math.radians(target_lat)
        delta_lon = math.radians(target_lon - point.lon)
        bearing = (math.degrees(math.atan2(math.sin(delta_lon) * math.cos(lat2), math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon))) + 360) % 360
        model_features["heading_error_deg"] = abs((point.heading - bearing + 180) % 360 - 180)

    for minutes in (1, 3, 5, 10):
        start = point.timestamp - timedelta(minutes=minutes)
        rows = [row for row in history if aware(row.timestamp) >= start]
        speeds = [float(row.speed) for row in rows]
        prefix = f"_{minutes}m"
        model_features[f"telemetry_count{prefix}"] = float(len(rows))
        model_features[f"valid_ratio{prefix}"] = 1.0 if rows else 0.0
        if speeds:
            model_features[f"speed_mean{prefix}"] = sum(speeds) / len(speeds)
            model_features[f"speed_std{prefix}"] = pstdev(speeds) if len(speeds) > 1 else 0.0
            model_features[f"speed_min{prefix}"] = min(speeds)
            model_features[f"speed_max{prefix}"] = max(speeds)
            model_features[f"speed_delta{prefix}"] = speeds[-1] - speeds[0]
            model_features[f"stationary_ratio{prefix}"] = sum(speed < 1 for speed in speeds) / len(speeds)
            model_features[f"movement_km{prefix}"] = sum(
                haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(rows, rows[1:])
            )
    return MLPredictionRequest(
        current_delay_min=delay,
        speed=point.speed,
        distance_to_stop_km=distance,
        hour=point.timestamp.hour,
        historical_delay_min=await historical_delay(session, point.vehicle_id),
        dwell_seconds=dwell,
        horizon_min=horizon,
        model_features=model_features,
    )
