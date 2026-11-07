from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from parking.database.db import get_db
from parking.database.models import ParkingSession, ParkingSessionStatusChoices
from parking.database.schema import ParkingSessionWithDurationOut

session_router = APIRouter(prefix="/sessions", tags=["Parking sessions"])

def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def calc_duration_seconds(entry_at: datetime, until: Optional[datetime] = None) -> int:
    end = as_utc(until) if until else datetime.now(timezone.utc)
    return max(int((end - as_utc(entry_at)).total_seconds()), 0)


def _human(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours} ч {minutes} мин"


def session_with_duration(session: ParkingSession) -> ParkingSessionWithDurationOut:
    seconds = calc_duration_seconds(session.entry_at, session.exit_at)
    base = ParkingSessionWithDurationOut.model_validate(
        {**{c: getattr(session, c) for c in ("id", "plate_number", "zone_id", "entry_event_id",
                                             "exit_event_id", "entry_at", "exit_at", "status")},
         "duration_seconds": seconds, "duration_human": _human(seconds)})
    return base


@session_router.get("/", response_model=List[ParkingSessionWithDurationOut])
def list_sessions(session_status: Optional[ParkingSessionStatusChoices] = Query(None, alias="status"),
                  zone_id: Optional[int] = None, plate_number: Optional[str] = None,
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    stmt = select(ParkingSession)
    if session_status is not None:
        stmt = stmt.where(ParkingSession.status == session_status)
    if zone_id is not None:
        stmt = stmt.where(ParkingSession.zone_id == zone_id)
    if plate_number:
        stmt = stmt.where(ParkingSession.plate_number == plate_number.upper().replace(" ", "").replace("-", ""))
    stmt = stmt.order_by(ParkingSession.entry_at.desc()).limit(limit).offset(offset)
    return [session_with_duration(s) for s in db.scalars(stmt).all()]


@session_router.get("/{session_id}", response_model=ParkingSessionWithDurationOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(ParkingSession, session_id)
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сессия не найдена")
    return session_with_duration(session)