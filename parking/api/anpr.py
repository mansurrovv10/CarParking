import io
import os
import re
import cv2
import secrets
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.security import APIKeyHeader
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from sqlalchemy.orm import Session
from parking.config import BASE_DIR
from parking.anpr.pipeline import process_image
from parking.api.vihicleEvent import recognize
from parking.database.db import get_db
from parking.database.models import Camera
from parking.database.schema import VehicleEventCreate


register_heif_opener()
load_dotenv(BASE_DIR / ".env")

api_key_header = APIKeyHeader(name="X-ANPR-Key", auto_error=False)


def authorize(api_key: str | None = Depends(api_key_header)):
    expected = os.getenv("ANPR_API_KEY")

    if not expected:
        raise HTTPException(503, "ANPR API key не настроен")

    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(401, "Неверный API key")


anpr_router = APIRouter(
    prefix="/anpr",
    tags=["ANPR"],
    dependencies=[Depends(authorize)]
)


def get_camera(db: Session, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)

    if not camera:
        raise HTTPException(404, "Камера не найдена")

    if not camera.is_active:
        raise HTTPException(409, "Камера отключена")

    return camera


def save_results(
    db: Session,
    camera_id: int,
    results: list[dict]
) -> list[dict]:

    camera = get_camera(db, camera_id)
    now = datetime.now(timezone.utc)
    processed = False

    for result in results:
        raw = (result.get("plate_raw") or "").strip()
        plate = result.get("plate_number")

        if not raw and not plate:
            continue

        confidence = result.get("confidence")

        event_data = VehicleEventCreate(
            event_key=uuid4().hex,
            camera_id=camera_id,
            plate_raw=raw[:30] or None,
            plate_number=plate,
            confidence=(
                Decimal(str(confidence))
                if confidence is not None else None
            ),
            detected_at=now
        )

        decision = recognize(data=event_data, db=db)
        processed = True

        result["event_id"] = decision.event.id
        result["decision"] = decision.decision
        result["reason"] = decision.reason
        result["session_id"] = decision.session_id

        result["barrier_command"] = (
            decision.barrier_command.model_dump(mode="json")
            if decision.barrier_command else None
        )

    if not processed:
        camera.last_seen_at = now
        db.commit()

    return results


def analyze_frame(
    db: Session,
    camera_id: int,
    image: Image.Image
) -> list[dict]:
    get_camera(db, camera_id)
    return save_results(db, camera_id, process_image(image))


@anpr_router.post("/image")
def recognize_image(
    camera_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    get_camera(db, camera_id)

    data = file.file.read(15 * 1024 * 1024 + 1)

    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Изображение больше 15 MB")

    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 20_000_000:
                raise HTTPException(413, "Слишком большое изображение")

            image = ImageOps.exif_transpose(source).convert("RGB")

    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "Неверный формат или повреждённое изображение")

    results = analyze_frame(db, camera_id, image)
    return {"source": "image", "results": results}


@anpr_router.post("/video")
def recognize_video(
    camera_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    get_camera(db, camera_id)

    max_mb = max(1, int(os.getenv("ANPR_MAX_VIDEO_MB", "2048")))
    frame_step = max(1, int(os.getenv("ANPR_FRAME_STEP", "5")))
    suffix = Path(file.filename or "").suffix.lower()[:16]

    path, cap = None, None

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            path = Path(tmp.name)
            size = 0

            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)

                if size > max_mb * 1024 * 1024:
                    raise HTTPException(413, f"Видео больше {max_mb} MB")

                tmp.write(chunk)

        if size == 0:
            raise HTTPException(400, "Пустой видеофайл")

        cap = cv2.VideoCapture(str(path))

        if not cap.isOpened():
            raise HTTPException(415, "Не удалось открыть видеопоток")

        candidates = {}
        frame_index = 0
        frames_checked = 0
        frames_with_detections = 0

        while True:
            ok, frame = cap.read()

            if not ok:
                break

            if frame_index % frame_step == 0:
                if frame.shape[0] * frame.shape[1] > 20_000_000:
                    raise HTTPException(413, "Слишком большое разрешение кадра")

                image = Image.fromarray(
                    cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                )

                detected = process_image(image)
                frames_checked += 1

                if detected:
                    frames_with_detections += 1

                for result in detected:
                    raw = result.get("plate_raw") or ""
                    plate = result.get("plate_number")
                    key = re.sub(r"[^A-Z0-9]", "", (plate or raw).upper())

                    if not key:
                        continue

                    if key not in candidates:
                        candidates[key] = {**result, "frames_seen": 1}
                    else:
                        current = candidates[key]
                        current["frames_seen"] += 1

                        if (result.get("confidence") or 0) > (
                            current.get("confidence") or 0
                        ):
                            count = current["frames_seen"]
                            current.update(result)
                            current["frames_seen"] = count

            frame_index += 1

        if frame_index == 0:
            raise HTTPException(415, "Не удалось декодировать видео")

        results = sorted(
            candidates.values(),
            key=lambda x: (
                x["plate_number"] is not None,
                x["frames_seen"],
                x.get("confidence") or 0
            ),
            reverse=True
        )

        save_results(db, camera_id, results)

        return {
            "source": "video",
            "frames_total": frame_index,
            "frames_checked": frames_checked,
            "frames_with_detections": frames_with_detections,
            "results": results
        }

    finally:
        if cap is not None:
            cap.release()

        if path is not None:
            path.unlink(missing_ok=True)


@anpr_router.post("/camera/snapshot")
def recognize_camera(db: Session = Depends(get_db)):
    source = os.getenv("ANPR_CAMERA_SOURCE")
    camera_id = os.getenv("ANPR_CAMERA_ID")

    if not source or not camera_id or not camera_id.isdecimal():
        raise HTTPException(503, "Камера ANPR не настроена")

    camera_id = int(camera_id)
    get_camera(db, camera_id)

    capture_source = int(source) if source.isdecimal() else source
    cap = cv2.VideoCapture(capture_source)

    try:
        if not cap.isOpened():
            raise HTTPException(503, "Камера недоступна")

        ok, frame = cap.read()

        if not ok:
            raise HTTPException(503, "Не удалось получить кадр")

        image = Image.fromarray(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )

        results = analyze_frame(db, camera_id, image)
        return {"source": "camera", "results": results}

    finally:
        cap.release()
