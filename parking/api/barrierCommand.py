from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from parking.database.db import get_db
from parking.database.models import (Barrier, BarrierCommand, BarrierCommandStatusChoices,
                                     BarrierCommandTypeChoices)
from parking.database.schema import BarrierCommandOut

barrier_command_router = APIRouter(prefix="/barrier-commands", tags=["Barrier commands"])


def create_open_command(db: Session, barrier: Barrier, idempotency_key: str,
                        event_id: Optional[int] = None, session_id: Optional[int] = None) -> BarrierCommand:
    existing = db.scalar(select(BarrierCommand).where(BarrierCommand.idempotency_key == idempotency_key))
    if existing:
        if existing.barrier_id != barrier.id:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "idempotency_key уже использован для другого шлагбаума")
        return existing

    command = BarrierCommand(barrier_id=barrier.id, event_id=event_id, session_id=session_id,
                             command=BarrierCommandTypeChoices.OPEN, idempotency_key=idempotency_key,
                             # MVP: команда сразу уходит в симулятор контроллера
                             status=BarrierCommandStatusChoices.SENT)
    db.add(command)
    db.flush()
    return command


@barrier_command_router.get("/", response_model=List[BarrierCommandOut])
def list_commands(barrier_id: Optional[int] = None,
                  command_status: Optional[BarrierCommandStatusChoices] = Query(None, alias="status"),
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    stmt = select(BarrierCommand)
    if barrier_id is not None:
        stmt = stmt.where(BarrierCommand.barrier_id == barrier_id)
    if command_status is not None:
        stmt = stmt.where(BarrierCommand.status == command_status)
    stmt = stmt.order_by(BarrierCommand.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@barrier_command_router.get("/{command_id}", response_model=BarrierCommandOut)
def get_command(command_id: int, db: Session = Depends(get_db)):
    command = db.get(BarrierCommand, command_id)
    if not command:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Команда не найдена")
    return command