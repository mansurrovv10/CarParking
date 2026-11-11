import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from parking.anpr.plate_parser import parse_plate
from parking.api.barrierCommand import create_open_command
from parking.api.parkingSession import as_utc, calc_duration_seconds, session_with_duration
from parking.api.parkingZone import zone_occupancy
from parking.database.db import get_db
from parking.database.models import (
    BarrierCommand, Camera, DirectionChoices, ParkingSession,
    ParkingSessionStatusChoices, ParkingZone, VehicleEvent,
    VehicleEventStatusChoices
)
from parking.database.schema import (
    BarrierCommandOut, PassageConfirm, PassageResult, RecognizeResult,
    VehicleEventCreate, VehicleEventJournalOut, VehicleEventOut
)


event_router = APIRouter(prefix="/events", tags=["Vehicle events"])
passage_router = APIRouter(prefix="/passages", tags=["Passages"])

CONFIDENCE_THRESHOLD = Decimal("0.90")
DUPLICATE_WINDOW = timedelta(seconds=10)


def normalize_plate(plate: Optional[str]) -> Optional[str]:
    if not plate:
        return None
    cleaned = re.sub(r"[^0-9A-ZА-Я]", "", plate.upper())
    return cleaned or None


def find_active_session(
    db: Session, plate: str, lock: bool = False
) -> Optional[ParkingSession]:
    stmt = select(ParkingSession).where(
        ParkingSession.plate_number == plate,
        ParkingSession.status == ParkingSessionStatusChoices.ACTIVE
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _command_for_event(db: Session, event_id: int) -> Optional[BarrierCommand]:
    return db.scalar(
        select(BarrierCommand)
        .where(BarrierCommand.event_id == event_id)
        .order_by(BarrierCommand.id.desc())
    )


def _duplicate_result(
    db: Session,
    event: VehicleEvent,
    reason: str = "Повторное событие"
) -> RecognizeResult:
    command = _command_for_event(db, event.id)

    return RecognizeResult(
        event=VehicleEventOut.model_validate(event),
        direction=event.camera.direction,
        decision="duplicate",
        reason=reason,
        barrier_command=(
            BarrierCommandOut.model_validate(command) if command else None
        ),
        session_id=command.session_id if command else None
    )


@event_router.post("/recognize", response_model=RecognizeResult)
def recognize(data: VehicleEventCreate, db: Session = Depends(get_db)):

    camera = db.scalar(
        select(Camera)
        .where(Camera.id == data.camera_id)
        .with_for_update()
    )

    if not camera:
        raise HTTPException(404, "Камера не найдена")

    if not camera.is_active:
        raise HTTPException(409, "Камера отключена")

    existing = db.scalar(
        select(VehicleEvent)
        .where(VehicleEvent.event_key == data.event_key)
    )

    if existing:
        return _duplicate_result(
            db, existing, "Этот event_key уже обработан"
        )

    parsed = parse_plate(data.plate_number or data.plate_raw or "")
    plate = parsed["plate_number"] if parsed else None
    now = datetime.now(timezone.utc)

    # Защита от повторного распознавания
    if (
        plate
        and data.confidence is not None
        and data.confidence >= CONFIDENCE_THRESHOLD
    ):
        duplicate = db.scalar(
            select(VehicleEvent)
            .where(
                VehicleEvent.camera_id == camera.id,
                VehicleEvent.plate_number == plate,
                VehicleEvent.processing_status ==
                    VehicleEventStatusChoices.RECOGNIZED,
                VehicleEvent.passage_confirmed_at.is_(None),
                VehicleEvent.detected_at >= now - DUPLICATE_WINDOW,
                VehicleEvent.detected_at <= now
            )
            .order_by(
                VehicleEvent.detected_at.desc(),
                VehicleEvent.id.desc()
            )
            .limit(1)
        )

        if duplicate:
            camera.last_seen_at = now
            result = _duplicate_result(
                db,
                duplicate,
                "Повторное распознавание в течение 10 секунд"
            )
            db.commit()
            return result

    # Создание события
    camera.last_seen_at = now

    event = VehicleEvent(
        **data.model_dump(exclude={"plate_number"}),
        plate_number=plate,
        processing_status=VehicleEventStatusChoices.PENDING
    )

    db.add(event)
    db.flush()

    direction = camera.direction
    zone = db.get(ParkingZone, camera.zone_id)

    barrier = (
        camera.barrier
        if camera.barrier and camera.barrier.is_active
        else None
    )

    decision = "needs_review"
    reason = None
    session: Optional[ParkingSession] = None

    # Проверка распознавания
    if plate is None:
        reason = "Номер не распознан"

    elif data.confidence is None or data.confidence < CONFIDENCE_THRESHOLD:
        reason = f"Низкая уверенность распознавания (< {CONFIDENCE_THRESHOLD})"

    elif not zone.is_active:
        reason = "Зона отключена"

    # Въезд автомобиля
    elif direction == DirectionChoices.ENTRY:
        if zone.occupied_count >= zone.capacity:
            reason = "Парковка заполнена"

        elif find_active_session(db, plate):
            reason = "У номера уже есть активная парковочная сессия"

        else:
            decision = "allow_entry"

    # Выезд автомобиля
    else:
        session = find_active_session(db, plate)

        if session is None or session.zone_id != zone.id:
            session = None
            reason = "Активная сессия для этого номера не найдена"

        else:
            decision = "allow_exit"

    # Создание команды шлагбаума
    command = None

    if decision == "needs_review":
        event.processing_status = VehicleEventStatusChoices.NEEDS_REVIEW

    else:
        event.processing_status = VehicleEventStatusChoices.RECOGNIZED

        if barrier:
            command = create_open_command(
                db=db,
                barrier=barrier,
                idempotency_key=f"auto-open:event:{event.id}",
                event_id=event.id,
                session_id=session.id if session else None
            )
        else:
            reason = "К камере не привязан активный шлагбаум"

    # Сохранение в Database
    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        existing = db.scalar(
            select(VehicleEvent)
            .where(VehicleEvent.event_key == data.event_key)
        )

        if existing:
            return _duplicate_result(
                db, existing, "Этот event_key уже обработан"
            )

        raise HTTPException(409, "Конфликт данных при сохранении")

    db.refresh(event)

    if command:
        db.refresh(command)

    return RecognizeResult(
        event=VehicleEventOut.model_validate(event),
        direction=direction,
        decision=decision,
        reason=reason,
        barrier_command=(
            BarrierCommandOut.model_validate(command)
            if command else None
        ),
        session_id=session.id if session else None,
        duration_seconds=(
            calc_duration_seconds(session.entry_at, event.detected_at)
            if session else None
        )
    )


@event_router.get("/", response_model=List[VehicleEventJournalOut])
def list_events(
    event_status: Optional[VehicleEventStatusChoices] = Query(None, alias="status"),
    camera_id: Optional[int] = None,
    direction: Optional[DirectionChoices] = None,
    plate_number: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    stmt = (
        select(VehicleEvent, Camera.direction)
        .join(Camera, VehicleEvent.camera_id == Camera.id)
    )

    if event_status is not None:
        stmt = stmt.where(VehicleEvent.processing_status == event_status)

    if camera_id is not None:
        stmt = stmt.where(VehicleEvent.camera_id == camera_id)

    if direction is not None:
        stmt = stmt.where(Camera.direction == direction)

    if plate_number:
        stmt = stmt.where(
            VehicleEvent.plate_number == normalize_plate(plate_number)
        )

    if date_from:
        stmt = stmt.where(VehicleEvent.detected_at >= date_from)

    if date_to:
        stmt = stmt.where(VehicleEvent.detected_at <= date_to)

    stmt = (
        stmt.order_by(VehicleEvent.detected_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return [
        VehicleEventJournalOut(
            **VehicleEventOut.model_validate(ev).model_dump(),
            direction=d
        )
        for ev, d in db.execute(stmt).all()
    ]


@event_router.get("/{event_id}", response_model=VehicleEventJournalOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(VehicleEvent, event_id)

    if not event:
        raise HTTPException(404, "Событие не найдено")

    return VehicleEventJournalOut(
        **VehicleEventOut.model_validate(event).model_dump(),
        direction=event.camera.direction
    )


class EventReview(BaseModel):
    action: Literal["approve", "reject"]
    plate_number: Optional[str] = None


@event_router.patch("/{event_id}/review", response_model=VehicleEventOut)
def review_event(
    event_id: int,
    data: EventReview,
    db: Session = Depends(get_db)
):
    event = db.get(VehicleEvent, event_id)

    if not event:
        raise HTTPException(404, "Событие не найдено")

    if event.processing_status != VehicleEventStatusChoices.NEEDS_REVIEW:
        raise HTTPException(409, "Событие не ожидает ручной проверки")

    if data.action == "reject":
        event.processing_status = VehicleEventStatusChoices.REJECTED

    else:
        plate = normalize_plate(data.plate_number) or event.plate_number

        if not plate:
            raise HTTPException(400, "Укажите номер для подтверждения")

        event.plate_number = plate
        event.processing_status = VehicleEventStatusChoices.RECOGNIZED

    db.commit()
    db.refresh(event)
    return event


@passage_router.post("/confirm", response_model=PassageResult)
def confirm_passage(
    data: PassageConfirm,
    db: Session = Depends(get_db)
):
    event = db.scalar(
        select(VehicleEvent)
        .where(VehicleEvent.id == data.event_id)
        .with_for_update()
    )

    if not event:
        raise HTTPException(404, "Событие не найдено")

    if event.passage_confirmed_at is not None:
        session = event.entry_session or event.exit_session

        if session is None:
            raise HTTPException(
                409, "Проезд подтверждён, но сессия не найдена"
            )

        return PassageResult(
            event=VehicleEventOut.model_validate(event),
            session=session_with_duration(session),
            occupancy=zone_occupancy(session.zone),
            already_confirmed=True
        )

    if event.processing_status != VehicleEventStatusChoices.RECOGNIZED:
        raise HTTPException(
            409,
            f"Нельзя подтвердить проезд: статус '{event.processing_status.value}'"
        )

    if not event.plate_number:
        raise HTTPException(400, "У события нет номера")

    camera = event.camera

    zone = db.scalar(
        select(ParkingZone)
        .where(ParkingZone.id == camera.zone_id)
        .with_for_update()
    )

    # Подтверждение въезда
    if camera.direction == DirectionChoices.ENTRY:
        if zone.occupied_count >= zone.capacity:
            raise HTTPException(409, "Парковка заполнена")

        if find_active_session(db, event.plate_number, lock=True):
            raise HTTPException(
                409, "У этого номера уже есть активная сессия"
            )

        session = ParkingSession(
            plate_number=event.plate_number,
            zone_id=zone.id,
            entry_event_id=event.id,
            entry_at=data.passage_confirmed_at,
            status=ParkingSessionStatusChoices.ACTIVE
        )

        db.add(session)
        db.flush()
        zone.occupied_count += 1

    # Подтверждение выезда
    else:
        session = find_active_session(
            db, event.plate_number, lock=True
        )

        if session is None or session.zone_id != zone.id:
            raise HTTPException(
                409, "Активная сессия для этого номера не найдена"
            )

        if as_utc(data.passage_confirmed_at) < as_utc(session.entry_at):
            raise HTTPException(
                400, "Время выезда раньше времени въезда"
            )

        session.status = ParkingSessionStatusChoices.CLOSED
        session.exit_at = data.passage_confirmed_at
        session.exit_event_id = event.id
        zone.occupied_count = max(zone.occupied_count - 1, 0)

    event.passage_confirmed_at = data.passage_confirmed_at
    event.passage_source = data.passage_source

    # Привязка команд к парковочной сессии
    db.execute(
        update(BarrierCommand)
        .where(
            BarrierCommand.event_id == event.id,
            BarrierCommand.session_id.is_(None)
        )
        .values(session_id=session.id)
    )

    try:
        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Конфликт данных парковочной сессии"
        )

    db.refresh(session)
    db.refresh(event)
    db.refresh(zone)

    return PassageResult(
        event=VehicleEventOut.model_validate(event),
        session=session_with_duration(session),
        occupancy=zone_occupancy(zone)
    )
