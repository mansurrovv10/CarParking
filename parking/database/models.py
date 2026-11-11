from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional
from sqlalchemy import (Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String,
                        func, text,)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from parking.database.db import Base


# ENUMS
class CameraTypeChoices(str, PyEnum):
    ANPR = "anpr"
    IP = "ip"

class DirectionChoices(str, PyEnum):
    ENTRY = "entry"
    EXIT = "exit"

class VehicleEventStatusChoices(str, PyEnum):
    PENDING = "pending"
    RECOGNIZED = "recognized"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"

class ParkingSessionStatusChoices(str, PyEnum):
    ACTIVE = "active"
    CLOSED = "closed"

class BarrierStatusChoices(str, PyEnum):
    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"

class BarrierCommandTypeChoices(str, PyEnum):
    OPEN = "open"
    CLOSE = "close"

class BarrierCommandStatusChoices(str, PyEnum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMEOUT = "timeout"

# 1. ПАРКОВОЧНЫЕ ЗОНЫ
class ParkingZone(Base):
    __tablename__ = "parking_zone"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parking_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    parking_name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (CheckConstraint("capacity >= 0", name="ck_zone_capacity"),
        CheckConstraint("occupied_count BETWEEN 0 AND capacity", name="ck_zone_occupancy"),)

    cameras: Mapped[List["Camera"]] = relationship("Camera", back_populates="zone")
    barriers: Mapped[List["Barrier"]] = relationship("Barrier", back_populates="zone")
    sessions: Mapped[List["ParkingSession"]] = relationship("ParkingSession", back_populates="zone")

# 2. ШЛАГБАУМЫ
class Barrier(Base):
    __tablename__ = "barrier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    zone_id: Mapped[int] = mapped_column(ForeignKey("parking_zone.id"), nullable=False)
    direction: Mapped[DirectionChoices] = mapped_column(Enum(DirectionChoices, name="direction_choices"),
                                                        nullable=False)
    status: Mapped[BarrierStatusChoices] = mapped_column(Enum(BarrierStatusChoices, name="barrier_status_choices"),
                                                         default=BarrierStatusChoices.UNKNOWN, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    zone: Mapped["ParkingZone"] = relationship("ParkingZone", back_populates="barriers")
    cameras: Mapped[List["Camera"]] = relationship("Camera", back_populates="barrier")
    commands: Mapped[List["BarrierCommand"]] = relationship("BarrierCommand", back_populates="barrier")


# 3. КАМЕРЫ
class Camera(Base):
    __tablename__ = "camera"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    camera_type: Mapped[CameraTypeChoices] = mapped_column(Enum(CameraTypeChoices, name="camera_type_choices"),
                                                           nullable=False)
    direction: Mapped[DirectionChoices] = mapped_column(Enum(DirectionChoices, name="direction_choices"),
                                                        nullable=False)

    zone_id: Mapped[int] = mapped_column(ForeignKey("parking_zone.id"), nullable=False)
    barrier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("barrier.id"), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    zone: Mapped["ParkingZone"] = relationship("ParkingZone", back_populates="cameras")
    barrier: Mapped[Optional["Barrier"]] = relationship("Barrier", back_populates="cameras")
    events: Mapped[List["VehicleEvent"]] = relationship("VehicleEvent", back_populates="camera")


# 4. СОБЫТИЯ РАСПОЗНАВАНИЯ
class VehicleEvent(Base):
    __tablename__ = "vehicle_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    plate_raw: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    plate_number: Mapped[Optional[str]] = mapped_column(String(30), index=True, nullable=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_status: Mapped[VehicleEventStatusChoices] = mapped_column(
        Enum(VehicleEventStatusChoices, name="vehicleeventstatuschoices"),
        default=VehicleEventStatusChoices.PENDING,
        nullable=False
    )

    passage_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    passage_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), index=True, nullable=False)

    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1",
                                      name="ck_vehicle_event_confidence"),)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="events")
    entry_session: Mapped[Optional["ParkingSession"]] = relationship("ParkingSession",
                                                                     back_populates="entry_event",
                                                                     foreign_keys="ParkingSession.entry_event_id")
    exit_session: Mapped[Optional["ParkingSession"]] = relationship("ParkingSession",
                                                                    back_populates="exit_event",
                                                                    foreign_keys="ParkingSession.exit_event_id")
    barrier_commands: Mapped[List["BarrierCommand"]] = relationship("BarrierCommand",
                                                                    back_populates="event")


# 5. ПАРКОВОЧНЫЕ СЕССИИ
class ParkingSession(Base):
    __tablename__ = "parking_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate_number: Mapped[str] = mapped_column(String(30), nullable=False)

    zone_id: Mapped[int] = mapped_column(ForeignKey("parking_zone.id"), nullable=False)
    entry_event_id: Mapped[int] = mapped_column(ForeignKey("vehicle_event.id"), unique=True, nullable=False)
    exit_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicle_event.id"), unique=True,
                                                         nullable=True)

    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True),nullable=True)
    status: Mapped[ParkingSessionStatusChoices] = mapped_column(Enum(ParkingSessionStatusChoices,
                                                                     name="parking_session_status_choices"),
                                                                default=ParkingSessionStatusChoices.ACTIVE,
                                                                nullable=False)

    __table_args__ = (Index("uq_active_parking_session_plate","plate_number", unique=True,
                            postgresql_where=text("status = 'ACTIVE'")),
        CheckConstraint("exit_at IS NULL OR exit_at >= entry_at", name="ck_session_exit_after_entry"),)

    zone: Mapped["ParkingZone"] = relationship("ParkingZone", back_populates="sessions")
    entry_event: Mapped["VehicleEvent"] = relationship("VehicleEvent", back_populates="entry_session",
                                                       foreign_keys=[entry_event_id])
    exit_event: Mapped[Optional["VehicleEvent"]] = relationship("VehicleEvent",
                                                                back_populates="exit_session",
                                                                foreign_keys=[exit_event_id])
    barrier_commands: Mapped[List["BarrierCommand"]] = relationship("BarrierCommand",
                                                                    back_populates="session")

# 6. КОМАНДЫ ШЛАГБАУМУ
class BarrierCommand(Base):
    __tablename__ = "barrier_command"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barrier_id: Mapped[int] = mapped_column(ForeignKey("barrier.id"), nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parking_session.id"), nullable=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicle_event.id"), nullable=True)
    command: Mapped[BarrierCommandTypeChoices] = mapped_column(Enum(BarrierCommandTypeChoices,
                                                                    name="barriercommandtypechoices"),
                                                               default=BarrierCommandTypeChoices.OPEN,
                                                               nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[BarrierCommandStatusChoices] = mapped_column(Enum(BarrierCommandStatusChoices,
                                                                     name="barrier_command_status_choices"),
                                                                default=BarrierCommandStatusChoices.PENDING,
                                                                nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    barrier: Mapped["Barrier"] = relationship("Barrier", back_populates="commands")
    session: Mapped[Optional["ParkingSession"]] = relationship("ParkingSession",
                                                               back_populates="barrier_commands")
    event: Mapped[Optional["VehicleEvent"]] = relationship("VehicleEvent",
                                                           back_populates="barrier_commands")