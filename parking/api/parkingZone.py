from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from parking.database.db import get_db
from parking.database.models import ParkingZone
from parking.database.schema import ParkingZoneCreate, ParkingZoneOut, ZoneOccupancyOut

zone_router = APIRouter(prefix="/zones", tags=["Parking zones"])

def zone_occupancy(zone: ParkingZone) -> ZoneOccupancyOut:
    return ZoneOccupancyOut(zone_id=zone.id, capacity=zone.capacity, occupied_count=zone.occupied_count,
                            free_count=max(zone.capacity - zone.occupied_count, 0))


@zone_router.post("/", response_model=ParkingZoneOut, status_code=status.HTTP_201_CREATED)
def create_zone(data: ParkingZoneCreate, db: Session = Depends(get_db)):
    zone = ParkingZone(**data.model_dump())
    db.add(zone)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Зона с таким parking_code уже существует")
    db.refresh(zone)
    return zone


@zone_router.get("/", response_model=List[ParkingZoneOut])
def list_zones(db: Session = Depends(get_db)):
    return db.scalars(select(ParkingZone).order_by(ParkingZone.id)).all()


@zone_router.get("/{zone_id}", response_model=ParkingZoneOut)
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.get(ParkingZone, zone_id)
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Зона не найдена")
    return zone


@zone_router.get("/{zone_id}/occupancy", response_model=ZoneOccupancyOut)
def get_zone_occupancy(zone_id: int, db: Session = Depends(get_db)):
    zone = db.get(ParkingZone, zone_id)
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Зона не найдена")
    return zone_occupancy(zone)