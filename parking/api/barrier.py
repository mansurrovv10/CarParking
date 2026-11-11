from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from parking.database.db import get_db
from parking.database.models import (Barrier, BarrierCommand, BarrierCommandStatusChoices,
                                     BarrierCommandTypeChoices, BarrierStatusChoices,
                                     ParkingSession, ParkingZone, VehicleEvent)
from parking.database.schema import (BarrierAckRequest, BarrierCommandOut, BarrierCreate,
                                     BarrierOpenRequest, BarrierOut)
from parking.api.barrierCommand import create_open_command

barrier_router = APIRouter(prefix="/barriers", tags=["Barriers"])


def _get_barrier_or_404(db: Session, barrier_id: int) -> Barrier:
    barrier = db.get(Barrier, barrier_id)
    if not barrier:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шлагбаум не найден")
    return barrier


@barrier_router.post("/", response_model=BarrierOut, status_code=status.HTTP_201_CREATED)
def create_barrier(data: BarrierCreate, db: Session = Depends(get_db)):
    if not db.get(ParkingZone, data.zone_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Зона не найдена")
    barrier = Barrier(**data.model_dump())
    db.add(barrier)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Шлагбаум с таким code уже существует")
    db.refresh(barrier)
    return barrier


@barrier_router.get("/", response_model=List[BarrierOut])
def list_barriers(zone_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(Barrier).order_by(Barrier.id)
    if zone_id is not None:
        stmt = stmt.where(Barrier.zone_id == zone_id)
    return db.scalars(stmt).all()


@barrier_router.get("/{barrier_id}", response_model=BarrierOut)
def get_barrier(barrier_id: int, db: Session = Depends(get_db)):
    return _get_barrier_or_404(db, barrier_id)


@barrier_router.post("/{barrier_id}/open", response_model=BarrierCommandOut)
def open_barrier(barrier_id: int, data: BarrierOpenRequest, db: Session = Depends(get_db)):
    barrier = _get_barrier_or_404(db, barrier_id)
    if not barrier.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Шлагбаум отключён")
    if data.event_id is not None and not db.get(VehicleEvent, data.event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    if data.session_id is not None and not db.get(ParkingSession, data.session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сессия не найдена")

    command = create_open_command(db, barrier, data.idempotency_key,
                                  event_id=data.event_id, session_id=data.session_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        command = db.scalar(select(BarrierCommand).where(
            BarrierCommand.idempotency_key == data.idempotency_key))
        if (command is None or command.barrier_id != barrier_id
                or command.command != BarrierCommandTypeChoices.OPEN
                or command.event_id != data.event_id or command.session_id != data.session_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Конфликт ключа команды")
    db.refresh(command)
    return command


@barrier_router.post("/{barrier_id}/ack", response_model=BarrierCommandOut)
def ack_barrier(barrier_id: int, data: BarrierAckRequest, db: Session = Depends(get_db)):
    barrier = _get_barrier_or_404(db, barrier_id)
    command = db.scalar(
        select(BarrierCommand).where(
            BarrierCommand.idempotency_key == data.idempotency_key,
            BarrierCommand.barrier_id == barrier.id
        ).with_for_update()
    )
    if not command:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Команда для этого шлагбаума не найдена")

    final_statuses = {BarrierCommandStatusChoices.ACKNOWLEDGED,
                      BarrierCommandStatusChoices.FAILED,
                      BarrierCommandStatusChoices.TIMEOUT}
    if command.status in final_statuses:
        return command

    now = datetime.now(timezone.utc)
    barrier.last_seen_at = now

    if data.result == "acknowledged":
        command.status = BarrierCommandStatusChoices.ACKNOWLEDGED
        command.acknowledged_at = now
        if command.command == BarrierCommandTypeChoices.OPEN:
            barrier.status = BarrierStatusChoices.OPEN
        elif command.command == BarrierCommandTypeChoices.CLOSE:
            barrier.status = BarrierStatusChoices.CLOSED
    elif data.result == "failed":
        command.status = BarrierCommandStatusChoices.FAILED
        command.acknowledged_at = now
        barrier.status = BarrierStatusChoices.UNKNOWN
    else:
        command.status = BarrierCommandStatusChoices.TIMEOUT
        barrier.status = BarrierStatusChoices.UNKNOWN

    db.commit()
    db.refresh(command)
    return command
