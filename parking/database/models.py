from sqlalchemy import (Boolean, CheckConstraint, DateTime, Enum, ForeignKey,Date,
                        Index, Integer, Numeric, String, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from parking.database.db import Base
from enum import Enum as PyEnum
from typing import List, Optional
from decimal import Decimal


class RoleChoices(str, PyEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


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


class PaymentStatusChoices(str, PyEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class BarrierStatusChoices(str, PyEnum):
    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"


class BarrierCommandTypeChoices(str, PyEnum):
    OPEN = "open"


class BarrierCommandStatusChoices(str, PyEnum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMEOUT = "timeout"

# 1. Пользователи
class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    password_hash: Mapped[str] = mapped_column(String(50))
    role: Mapped[RoleChoices] = mapped_column(Enum(RoleChoices), default=RoleChoices.OPERATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[date] = mapped_column(Date, default=date.today)

    audit_logs: Mapped[List['AuditLog']] = relationship('AuditLog', back_populates='actor')


# 2. Парковочные зоны
class ParkingZone(Base):
    __tablename__ = 'parking_zone'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parking_code: Mapped[str] = mapped_column(String(30), unique=True)
    parking_name: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int] = mapped_column(Integer)
    occupied_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint('capacity >= 0', name='ck_zone_capacity'),
        CheckConstraint('occupied_count BETWEEN 0 AND capacity', name='ck_zone_occupancy'),
    )

    cameras: Mapped[List['Camera']] = relationship('Camera', back_populates='zone')
    barriers: Mapped[List['Barrier']] = relationship('Barrier', back_populates='zone')
    sessions: Mapped[List['ParkingSession']] = relationship('ParkingSession', back_populates='zone')


# 3. Шлагбаумы
class Barrier(Base):
    __tablename__ = 'barrier'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey('parking_zone.id'))
    direction: Mapped[DirectionChoices] = mapped_column(Enum(DirectionChoices, name='direction_choices'))
    status: Mapped[BarrierStatusChoices] = mapped_column(Enum(BarrierStatusChoices, name='barrier_status_choices'),
                                                         default=BarrierStatusChoices.UNKNOWN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    zone: Mapped[ParkingZone] = relationship(ParkingZone, back_populates='barriers')
    cameras: Mapped[List['Camera']] = relationship('Camera', back_populates='barrier')
    commands: Mapped[List['BarrierCommand']] = relationship('BarrierCommand', back_populates='barrier')


# 4. Камеры
class Camera(Base):
    __tablename__ = 'camera'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    camera_type: Mapped[CameraTypeChoices] = mapped_column(Enum(CameraTypeChoices, name='camera_type_choices'))
    direction: Mapped[DirectionChoices] = mapped_column(Enum(DirectionChoices, name='direction_choices'))
    zone_id: Mapped[int] = mapped_column(ForeignKey('parking_zone.id'))
    barrier_id: Mapped[Optional[int]] = mapped_column(ForeignKey('barrier.id'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    zone: Mapped[ParkingZone] = relationship(ParkingZone, back_populates='cameras')
    barrier: Mapped[Optional[Barrier]] = relationship(Barrier, back_populates='cameras')
    events: Mapped[List['VehicleEvent']] = relationship('VehicleEvent', back_populates='camera')


# 5. События распознавания
class VehicleEvent(Base):
    __tablename__ = 'vehicle_event'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey('camera.id'), index=True)
    plate_raw: Mapped[Optional[str]] = mapped_column(String(30))
    plate_number: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[VehicleEventStatusChoices] = mapped_column(Enum(VehicleEventStatusChoices),
                                                                         default=VehicleEventStatusChoices.PENDING)
    passage_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    passage_source: Mapped[Optional[str]] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_vehicle_event_confidence'),
    )

    camera: Mapped[Camera] = relationship(Camera, back_populates='events')
    entry_session: Mapped[Optional['ParkingSession']] = relationship('ParkingSession', back_populates='entry_event', foreign_keys='ParkingSession.entry_event_id')
    exit_session: Mapped[Optional['ParkingSession']] = relationship('ParkingSession', back_populates='exit_event', foreign_keys='ParkingSession.exit_event_id')
    barrier_commands: Mapped[List['BarrierCommand']] = relationship('BarrierCommand', back_populates='event')


# 6. Тарифы
class Tariff(Base):
    __tablename__ = 'tariff'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    period_minutes: Mapped[int] = mapped_column(Integer)
    price_per_period: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    free_minutes: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint('period_minutes > 0', name='ck_tariff_period_minutes'),
        CheckConstraint('price_per_period >= 0', name='ck_tariff_price'),
        CheckConstraint('free_minutes >= 0', name='ck_tariff_free_minutes'),
        CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='ck_tariff_valid_dates'),
    )

    sessions: Mapped[List['ParkingSession']] = relationship('ParkingSession', back_populates='tariff')


# 7. Парковочные сессии
class ParkingSession(Base):
    __tablename__ = 'parking_session'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate_number: Mapped[str] = mapped_column(String(30))
    zone_id: Mapped[int] = mapped_column(ForeignKey('parking_zone.id'))
    tariff_id: Mapped[int] = mapped_column(ForeignKey('tariff.id'))
    entry_event_id: Mapped[int] = mapped_column(ForeignKey('vehicle_event.id'), unique=True)
    exit_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey('vehicle_event.id'), unique=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[ParkingSessionStatusChoices] = mapped_column(Enum(ParkingSessionStatusChoices), default=ParkingSessionStatusChoices.ACTIVE)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    exit_allowed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index('uq_active_parking_session_plate', 'plate_number', unique=True, postgresql_where=text("status = 'ACTIVE'")),
        CheckConstraint('total_amount IS NULL OR total_amount >= 0', name='ck_session_total_amount'),
        CheckConstraint('exit_at IS NULL OR exit_at >= entry_at', name='ck_session_exit_after_entry'),
    )

    zone: Mapped[ParkingZone] = relationship(ParkingZone, back_populates='sessions')
    tariff: Mapped[Tariff] = relationship(Tariff, back_populates='sessions')
    entry_event: Mapped[VehicleEvent] = relationship(VehicleEvent, back_populates='entry_session', foreign_keys=[entry_event_id])
    exit_event: Mapped[Optional[VehicleEvent]] = relationship(VehicleEvent, back_populates='exit_session', foreign_keys=[exit_event_id])
    payments: Mapped[List['Payment']] = relationship('Payment', back_populates='session')
    barrier_commands: Mapped[List['BarrierCommand']] = relationship('BarrierCommand', back_populates='session')


# 8. Платежи
class Payment(Base):
    __tablename__ = 'payment'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('parking_session.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default='KGS')
    provider: Mapped[str] = mapped_column(String(50))
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[PaymentStatusChoices] = mapped_column(Enum(PaymentStatusChoices), default=PaymentStatusChoices.PENDING)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('provider', 'provider_transaction_id', name='uq_payment_provider_transaction'),
        CheckConstraint('amount >= 0', name='ck_payment_amount'),
    )

    session: Mapped[ParkingSession] = relationship(ParkingSession, back_populates='payments')


# 9. Команды шлагбауму
class BarrierCommand(Base):
    __tablename__ = 'barrier_command'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barrier_id: Mapped[int] = mapped_column(ForeignKey('barrier.id'))
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey('parking_session.id'))
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey('vehicle_event.id'))
    command: Mapped[BarrierCommandTypeChoices] = mapped_column(Enum(BarrierCommandTypeChoices), default=BarrierCommandTypeChoices.OPEN)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[BarrierCommandStatusChoices] = mapped_column(Enum(BarrierCommandStatusChoices), default=BarrierCommandStatusChoices.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    barrier: Mapped[Barrier] = relationship(Barrier, back_populates='commands')
    session: Mapped[Optional[ParkingSession]] = relationship(ParkingSession, back_populates='barrier_commands')
    event: Mapped[Optional[VehicleEvent]] = relationship(VehicleEvent, back_populates='barrier_commands')


# 10. Журнал действий
class AuditLog(Base):
    __tablename__ = 'audit_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey('user.id'))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped[Optional[User]] = relationship(User, back_populates='audit_logs')
