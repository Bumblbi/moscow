from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import get_settings
from .database import SessionLocal, create_schema, get_session
from .models import Prediction, Route, Schedule, Stop, TelematicsHistory, Vehicle
from .schemas import IngestResult, PredictionOut, TelematicsBatch, TelematicsPoint, VehicleOut
from .services import (
    Cache,
    PredictionClient,
    build_features,
    calculate_delay,
    latest_prediction,
    risk_level,
    vehicle_output,
)

settings = get_settings()
cache = Cache(settings.redis_url)
prediction_client = PredictionClient(settings)


class SocketHub:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, socket: WebSocket) -> None:
        await socket.accept()
        self.connections.add(socket)

    def disconnect(self, socket: WebSocket) -> None:
        self.connections.discard(socket)

    async def broadcast(self, payload: dict) -> None:
        stale: list[WebSocket] = []
        for socket in self.connections:
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(socket)
        for socket in stale:
            self.disconnect(socket)


hub = SocketHub()


async def seed_demo() -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(func.count(Route.id))):
            return
        route = Route(route_number="М2", name="Фили - Рижский вокзал")
        stops = [
            Stop(name="Библиотека им. Ленина", lat=55.7522, lon=37.6156),
            Stop(name="Охотный Ряд", lat=55.7577, lon=37.6159),
            Stop(name="Театральная площадь", lat=55.7590, lon=37.6205),
        ]
        session.add_all([route, *stops])
        await session.flush()
        start = datetime.now(UTC).replace(second=0, microsecond=0)
        for index, stop in enumerate(stops, 1):
            arrival = start + timedelta(minutes=(index - 1) * 6)
            session.add(
                Schedule(
                    route_id=route.id,
                    trip_id="M2-001",
                    stop_id=stop.id,
                    stop_sequence=index,
                    planned_arrival=arrival,
                    planned_departure=arrival + timedelta(minutes=1),
                )
            )
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_schema()
    if settings.seed_demo_data:
        await seed_demo()
    yield
    await cache.close()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
PREFIX = "/api/v1"


async def ingest(point: TelematicsPoint, session: AsyncSession) -> IngestResult:
    route = await session.get(Route, point.route_id)
    if not route:
        raise HTTPException(status_code=422, detail=f"route {point.route_id} does not exist")
    if point.nearest_stop_id and not await session.get(Stop, point.nearest_stop_id):
        raise HTTPException(status_code=422, detail=f"stop {point.nearest_stop_id} does not exist")
    vehicle = await session.get(Vehicle, point.vehicle_id)
    delay = await calculate_delay(session, point)
    now = datetime.now(UTC)
    if vehicle is None:
        vehicle = Vehicle(id=point.vehicle_id, route_id=point.route_id, updated_at=now)
        session.add(vehicle)
    vehicle.route_id = point.route_id
    vehicle.trip_id = point.trip_id
    vehicle.last_lat = point.lat
    vehicle.last_lon = point.lon
    vehicle.last_speed = point.speed
    vehicle.last_heading = point.heading
    vehicle.last_timestamp = point.timestamp
    vehicle.current_delay_min = delay
    vehicle.nearest_stop_id = point.nearest_stop_id
    vehicle.updated_at = now
    await session.flush()
    session.add(
        TelematicsHistory(
            vehicle_id=point.vehicle_id,
            route_id=point.route_id,
            timestamp=point.timestamp,
            lat=point.lat,
            lon=point.lon,
            speed=point.speed,
            heading=point.heading,
            nearest_stop_id=point.nearest_stop_id,
            door_status=point.door_status,
        )
    )
    features = await build_features(session, point, delay, settings.prediction_horizon_min)
    predicted = await prediction_client.predict(features)
    prediction = Prediction(
        vehicle_id=point.vehicle_id,
        predicted_at=now,
        horizon_min=settings.prediction_horizon_min,
        probability=predicted.response.probability,
        predicted_delay_min=predicted.response.predicted_delay_min,
        risk_level=risk_level(predicted.response.probability),
        reason=predicted.response.reason,
        model_version=predicted.response.model_version,
        latency_ms=predicted.latency_ms,
    )
    session.add(prediction)
    await session.commit()
    vehicle = await session.scalar(
        select(Vehicle).where(Vehicle.id == point.vehicle_id).options(selectinload(Vehicle.route))
    )
    assert vehicle is not None
    output = vehicle_output(vehicle, prediction)
    await cache.set_vehicle(output)
    await hub.broadcast({"type": "vehicle.updated", "vehicle": output.model_dump(mode="json")})
    return IngestResult(vehicle=output, prediction=PredictionOut.model_validate(prediction))


@app.get(f"{PREFIX}/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    database_ok = (await session.scalar(select(func.count(Route.id)))) is not None
    ml_service_ok = await prediction_client.health()
    return {
        "status": "ok" if database_ok and ml_service_ok else "degraded",
        "database": database_ok,
        "redis": await cache.ping(),
        "ml_service": settings.ml_service_url,
        "ml_service_ok": ml_service_ok,
    }


@app.post(f"{PREFIX}/telematics", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def post_telematics(point: TelematicsPoint, session: AsyncSession = Depends(get_session)) -> IngestResult:
    return await ingest(point, session)


@app.post(f"{PREFIX}/telematics/batch")
async def post_telematics_batch(batch: TelematicsBatch, session: AsyncSession = Depends(get_session)) -> dict:
    results = [await ingest(point, session) for point in batch.points]
    return {"processed": len(results), "results": results}


@app.get(f"{PREFIX}/vehicles")
async def vehicles(
    route_id: int | None = None,
    risk: str | None = Query(default=None, alias="risk_level"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    query = select(Vehicle).options(selectinload(Vehicle.route)).order_by(Vehicle.updated_at.desc()).limit(limit)
    if route_id:
        query = query.where(Vehicle.route_id == route_id)
    items = []
    for vehicle in (await session.scalars(query)).all():
        output = vehicle_output(vehicle, await latest_prediction(session, vehicle.id))
        if not risk or output.risk_level == risk:
            items.append(output)
    return {"vehicles": items, "total": len(items)}


@app.get(f"{PREFIX}/vehicles/{{vehicle_id}}", response_model=VehicleOut)
async def vehicle_detail(vehicle_id: str, session: AsyncSession = Depends(get_session)) -> VehicleOut:
    vehicle = await session.scalar(select(Vehicle).where(Vehicle.id == vehicle_id).options(selectinload(Vehicle.route)))
    if not vehicle:
        raise HTTPException(404, "vehicle not found")
    return vehicle_output(vehicle, await latest_prediction(session, vehicle_id))


@app.get(f"{PREFIX}/vehicles/{{vehicle_id}}/prediction")
async def vehicle_predictions(
    vehicle_id: str, limit: int = Query(default=50, ge=1, le=500), session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Vehicle, vehicle_id):
        raise HTTPException(404, "vehicle not found")
    rows = (
        await session.scalars(
            select(Prediction)
            .where(Prediction.vehicle_id == vehicle_id)
            .order_by(Prediction.predicted_at.desc())
            .limit(limit)
        )
    ).all()
    return {
        "latest": PredictionOut.model_validate(rows[0]) if rows else None,
        "history": [PredictionOut.model_validate(row) for row in rows],
    }


@app.get(f"{PREFIX}/vehicles/{{vehicle_id}}/history")
async def vehicle_history(
    vehicle_id: str, limit: int = Query(default=100, ge=1, le=1000), session: AsyncSession = Depends(get_session)
) -> dict:
    rows = (
        await session.scalars(
            select(TelematicsHistory)
            .where(TelematicsHistory.vehicle_id == vehicle_id)
            .order_by(TelematicsHistory.timestamp.desc())
            .limit(limit)
        )
    ).all()
    if not rows and not await session.get(Vehicle, vehicle_id):
        raise HTTPException(404, "vehicle not found")
    return {
        "vehicle_id": vehicle_id,
        "points": [
            {
                "timestamp": row.timestamp,
                "lat": row.lat,
                "lon": row.lon,
                "speed": row.speed,
                "heading": row.heading,
                "nearest_stop_id": row.nearest_stop_id,
                "door_status": row.door_status,
            }
            for row in rows
        ],
    }


@app.get(f"{PREFIX}/routes")
async def routes(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.scalars(select(Route).order_by(Route.route_number))).all()
    return {
        "routes": [
            {"id": row.id, "route_number": row.route_number, "name": row.name, "is_active": row.is_active}
            for row in rows
        ]
    }


async def route_summary(route_id: int, session: AsyncSession) -> dict:
    route = await session.get(Route, route_id)
    if not route:
        raise HTTPException(404, "route not found")
    vehicle_rows = (
        await session.scalars(select(Vehicle).where(Vehicle.route_id == route_id).options(selectinload(Vehicle.route)))
    ).all()
    outputs = [vehicle_output(vehicle, await latest_prediction(session, vehicle.id)) for vehicle in vehicle_rows]
    probabilities = [item.probability for item in outputs if item.probability is not None]
    return {
        "route_id": route.id,
        "route_number": route.route_number,
        "name": route.name,
        "average_probability": round(sum(probabilities) / len(probabilities), 4) if probabilities else 0.0,
        "high_risk_count": sum(item.risk_level == "high" for item in outputs),
        "vehicle_count": len(outputs),
        "vehicles": outputs,
    }


@app.get(f"{PREFIX}/routes/{{route_id}}")
async def route_detail(route_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    return await route_summary(route_id, session)


@app.get(f"{PREFIX}/routes/{{route_id}}/vehicles")
async def route_vehicles(route_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    summary = await route_summary(route_id, session)
    return {"vehicles": summary.pop("vehicles"), "total": summary["vehicle_count"]}


@app.get(f"{PREFIX}/routes/{{route_id}}/risk")
async def route_risk(route_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    summary = await route_summary(route_id, session)
    summary.pop("vehicles")
    return summary


@app.get(f"{PREFIX}/schedules")
async def schedules(
    route_id: int | None = None, trip_id: str | None = None, session: AsyncSession = Depends(get_session)
) -> dict:
    query = select(Schedule, Stop).join(Stop, Schedule.stop_id == Stop.id).order_by(Schedule.planned_arrival)
    if route_id:
        query = query.where(Schedule.route_id == route_id)
    if trip_id:
        query = query.where(Schedule.trip_id == trip_id)
    rows = (await session.execute(query)).all()
    return {
        "schedules": [
            {
                "id": schedule.id,
                "route_id": schedule.route_id,
                "trip_id": schedule.trip_id,
                "stop_id": schedule.stop_id,
                "stop_name": stop.name,
                "stop_lat": stop.lat,
                "stop_lon": stop.lon,
                "stop_sequence": schedule.stop_sequence,
                "planned_arrival": schedule.planned_arrival,
                "planned_departure": schedule.planned_departure,
            }
            for schedule, stop in rows
        ],
        "total": len(rows),
    }


@app.get(f"{PREFIX}/stats")
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    vehicle_count = await session.scalar(select(func.count(Vehicle.id))) or 0
    latest_predictions = (
        select(Prediction.vehicle_id, func.max(Prediction.predicted_at).label("predicted_at"))
        .group_by(Prediction.vehicle_id)
        .subquery()
    )
    current_predictions = select(Prediction).join(
        latest_predictions,
        (Prediction.vehicle_id == latest_predictions.c.vehicle_id)
        & (Prediction.predicted_at == latest_predictions.c.predicted_at),
    )
    current_rows = (await session.scalars(current_predictions)).all()
    high_risk = sum(row.risk_level == "high" for row in current_rows)
    average_delay = (
        sum(row.predicted_delay_min for row in current_rows) / len(current_rows) if current_rows else 0.0
    )
    average_latency = await session.scalar(select(func.avg(Prediction.latency_ms))) or 0.0
    return {
        "vehicle_count": vehicle_count,
        "high_risk_predictions": high_risk,
        "average_predicted_delay_min": round(float(average_delay), 2),
        "average_ml_latency_ms": round(float(average_latency), 2),
        "websocket_clients": len(hub.connections),
    }


@app.websocket(f"{PREFIX}/ws/updates")
async def websocket_updates(socket: WebSocket) -> None:
    await hub.connect(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(socket)
