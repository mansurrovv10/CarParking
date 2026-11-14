"""Read-only ANPR demo endpoints for the single-screen virtual barrier UI.

No real barrier commands, vehicle events, or parking sessions are written here.
"""

import io
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from parking.anpr.pipeline import process_image
from parking.anpr.plate_parser import normalize_plate, parse_plate
from parking.database.db import get_db
from parking.database.models import (
    Camera, DirectionChoices, ParkingSession, ParkingSessionStatusChoices,
    VehicleEvent, VehicleEventStatusChoices,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

router = APIRouter(prefix="/virtual", tags=["Virtual barrier"])
key_header = APIKeyHeader(name="X-ANPR-Key", auto_error=False)


def authorize(key: str | None = Depends(key_header)):
    expected = os.getenv("ANPR_API_KEY", "")
    if not expected:
        raise HTTPException(503, "ANPR_API_KEY не настроен")
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "Неверный X-ANPR-Key")


def get_camera(db: Session) -> Camera:
    camera_id = os.getenv("ANPR_BARRIER_CAMERA_ID", "")
    if not camera_id.isdecimal():
        raise HTTPException(503, "ANPR_BARRIER_CAMERA_ID не настроен")
    camera = db.get(Camera, int(camera_id))
    if camera is None:
        raise HTTPException(404, "Камера с таким ID отсутствует в БД")
    if not camera.is_active:
        raise HTTPException(409, "Камера отключена")
    return camera


def context_data(db: Session, camera: Camera) -> dict:
    zone = camera.zone
    barrier = camera.barrier
    recent = db.scalars(select(VehicleEvent).where(VehicleEvent.camera_id == camera.id)
                        .order_by(VehicleEvent.detected_at.desc()).limit(7)).all()
    return {
        "camera": {"id": camera.id, "name": camera.name, "code": camera.code,
                   "direction": camera.direction.value},
        "zone": {"id": zone.id, "name": zone.parking_name, "capacity": zone.capacity,
                 "occupied": zone.occupied_count, "free": max(0, zone.capacity - zone.occupied_count),
                 "active": zone.is_active},
        "barrier": {"id": barrier.id, "code": barrier.code, "active": barrier.is_active}
        if barrier else None,
        "events": [{"id": item.id, "plate": item.plate_number or item.plate_raw or "—",
                    "status": item.processing_status.value,
                    "at": item.detected_at.isoformat()} for item in recent],
    }


@router.get("/", include_in_schema=False)
def page():
    return FileResponse(Path(__file__).resolve().parents[1] / "static" / "operator.html")


@router.get("/context", dependencies=[Depends(authorize)])
def context(db: Session = Depends(get_db)):
    return context_data(db, get_camera(db))


@router.post("/analyze", dependencies=[Depends(authorize)])
async def analyze(file: UploadFile = File(...), db: Session = Depends(get_db)):
    camera = get_camera(db)
    data = await file.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Максимальный размер кадра — 12 МБ")

    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 20_000_000:
                raise HTTPException(413, "Слишком большое разрешение изображения")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "Неверное изображение")

    detected = process_image(image)
    response = {"allowed": False, "decision": "needs_review", "reason": "Номер не обнаружен",
                "plate_visible": bool(detected), "result": None, "db": {}, "detected_count": len(detected)}

    if len(detected) != 1:
        if len(detected) > 1:
            response["reason"] = "В кадре несколько номеров — требуется отдельная проверка"
        return response

    item = detected[0]
    plate = normalize_plate(item.get("plate_number") or "")
    confidence = float(item.get("confidence") or 0)
    yolo_confidence = float(item.get("yolo_confidence") or 0)
    ocr_status = item.get("ocr_status")
    response["result"] = {"plate_raw": item.get("plate_raw") or "", "plate_number": plate or None,
                          "confidence": confidence, "yolo_confidence": yolo_confidence,
                          "ocr_status": ocr_status or "UNVERIFIED", "bbox": item.get("bbox")}

    # Don't infer an access decision from raw OCR or regional guesses.
    parsed = parse_plate(plate) if plate else None
    if not parsed or parsed["plate_number"] != plate or ocr_status != "FORMAT_VALID":
        response["reason"] = "OCR не подтвердил полный номер и регион"
        return response
    if confidence < 0.85 or yolo_confidence < 0.80:
        response["reason"] = "Недостаточная уверенность YOLO / OCR (требуется 0.85 / 0.80)"
        return response

    zone = camera.zone
    barrier = camera.barrier
    active_session = db.scalar(select(ParkingSession).where(
        ParkingSession.plate_number == plate,
        ParkingSession.status == ParkingSessionStatusChoices.ACTIVE,
    ))
    known_event = db.scalar(select(VehicleEvent.id).where(
        VehicleEvent.plate_number == plate,
        VehicleEvent.processing_status == VehicleEventStatusChoices.RECOGNIZED,
    ).limit(1))
    response["db"] = {"plate_in_events": known_event is not None,
                      "active_session": active_session is not None,
                      "zone_free": max(0, zone.capacity - zone.occupied_count),
                      "direction": camera.direction.value}

    if not zone.is_active:
        response["reason"] = "Парковочная зона отключена"
    elif not barrier or not barrier.is_active:
        response["reason"] = "Нет активного шлагбаума у камеры"
    elif camera.direction == DirectionChoices.ENTRY:
        if active_session:
            response["reason"] = "Автомобиль уже находится на парковке"
        elif zone.occupied_count >= zone.capacity:
            response["reason"] = "На парковке нет свободных мест"
        elif os.getenv("ANPR_VIRTUAL_REQUIRE_KNOWN", "1") == "1" and known_event is None:
            response["reason"] = "Номер отсутствует среди подтверждённых событий БД"
        else:
            response.update(allowed=True, decision="allow_entry",
                            reason="БД проверена: проезд на въезд разрешён")
    else:
        if not active_session or active_session.zone_id != zone.id:
            response["reason"] = "В БД нет активной парковочной сессии для выезда"
        else:
            response.update(allowed=True, decision="allow_exit",
                            reason="БД проверена: активная сессия найдена, выезд разрешён")

    # Crucially, no database write and no physical barrier open command.
    return response
