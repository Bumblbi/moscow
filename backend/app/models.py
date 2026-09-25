from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Stop(Base):
    __tablename__ = "stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (Index("idx_schedules_route_trip", "route_id", "trip_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    trip_id: Mapped[str] = mapped_column(String(50))
    stop_id: Mapped[int] = mapped_column(ForeignKey("stops.id"))
    stop_sequence: Mapped[int] = mapped_column(Integer)
    planned_arrival: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    trip_id: Mapped[str | None] = mapped_column(String(50))
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lon: Mapped[float | None] = mapped_column(Float)
    last_speed: Mapped[float | None] = mapped_column(Float)
    last_heading: Mapped[float | None] = mapped_column(Float)
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_delay_min: Mapped[float] = mapped_column(Float, default=0.0)
    nearest_stop_id: Mapped[int | None] = mapped_column(ForeignKey("stops.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    route: Mapped[Route] = relationship()


class TelematicsHistory(Base):
    __tablename__ = "telematics_history"
    __table_args__ = (Index("idx_telematics_vehicle_time", "vehicle_id", "timestamp"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"))
    route_id: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    speed: Mapped[float] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    nearest_stop_id: Mapped[int | None] = mapped_column(Integer)
    door_status: Mapped[str | None] = mapped_column(String(20))


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (Index("idx_predictions_vehicle_time", "vehicle_id", "predicted_at"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_min: Mapped[int] = mapped_column(Integer, default=15)
    probability: Mapped[float] = mapped_column(Float)
    predicted_delay_min: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(255))
    model_version: Mapped[str] = mapped_column(String(50))
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
