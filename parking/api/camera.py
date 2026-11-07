from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from parking.database.db import get_db
from parking.database.models import Barrier, Camera, DirectionChoices, ParkingZone
from parking.database.schema import CameraCreate, CameraOut

camera_router = APIRouter(prefix="/cameras", tags=["Cameras"])

@camera_router.post("/", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(data: CameraCreate, db: Session = Depends(get_db)):
    if not db.get(ParkingZone, data.zone_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Зона не найдена")

    if data.barrier_id is not None:
        barrier = db.get(Barrier, data.barrier_id)
        if not barrier:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Шлагбаум не найден")
        if barrier.zone_id != data.zone_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Шлагбаум находится в другой зоне")
        if barrier.direction != data.direction:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Направление камеры и шлагбаума не совпадает")

    camera = Camera(**data.model_dump())
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Камера с таким code уже существует")
    db.refresh(camera)
    return camera


@camera_router.get("/", response_model=List[CameraOut])
def list_cameras(zone_id: Optional[int] = None, direction: Optional[DirectionChoices] = None,
                 db: Session = Depends(get_db)):
    stmt = select(Camera).order_by(Camera.id)
    if zone_id is not None:
        stmt = stmt.where(Camera.zone_id == zone_id)
    if direction is not None:
        stmt = stmt.where(Camera.direction == direction)
    return db.scalars(stmt).all()


@camera_router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Камера не найдена")
    return camera