from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from parking.database.models import (CameraTypeChoices, DirectionChoices, VehicleEventStatusChoices,
                                     ParkingSessionStatusChoices, BarrierStatusChoices, BarrierCommandTypeChoices,
                                     BarrierCommandStatusChoices,)

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

# 1. PARKING ZONE
class ParkingZoneCreate(BaseModel):
    parking_code: str
    parking_name: str
    capacity: int = Field(ge=0)

class ParkingZoneOut(BaseSchema):
    id: int
    parking_code: str
    parking_name: str
    capacity: int
    occupied_count: int
    is_active: bool

# 2. BARRIER
class BarrierCreate(BaseModel):
    code: str
    zone_id: int
    direction: DirectionChoices

class BarrierOut(BaseSchema):
    id: int
    code: str
    zone_id: int
    direction: DirectionChoices
    status: BarrierStatusChoices
    is_active: bool
    last_seen_at: Optional[datetime] = None

# 3. CAMERA
class CameraCreate(BaseModel):
    code: str
    name: str
    camera_type: CameraTypeChoices
    direction: DirectionChoices
    zone_id: int
    barrier_id: Optional[int] = None

class CameraOut(BaseSchema):
    id: int
    code: str
    name: str
    camera_type: CameraTypeChoices
    direction: DirectionChoices
    zone_id: int
    barrier_id: Optional[int] = None
    is_active: bool
    last_seen_at: Optional[datetime] = None

# 4. VEHICLE EVENT
class VehicleEventCreate(BaseModel):
    camera_id: int
    event_key: str
    plate_raw: Optional[str] = None
    plate_number: Optional[str] = None
    confidence: Optional[Decimal] = Field(
        default=None,
        ge=0,
        le=1
    )
    image_path: Optional[str] = None
    detected_at: datetime

class VehicleEventOut(BaseSchema):
    id: int
    event_key: str
    camera_id: int
    plate_raw: Optional[str] = None
    plate_number: Optional[str] = None
    confidence: Optional[Decimal] = None
    image_path: Optional[str] = None
    detected_at: datetime
    processing_status: VehicleEventStatusChoices
    passage_confirmed_at: Optional[datetime] = None
    passage_source: Optional[str] = None

# 5. PARKING SESSION
class ParkingSessionCreate(BaseModel):
    plate_number: str
    zone_id: int
    entry_event_id: int
    entry_at: datetime

class ParkingSessionOut(BaseSchema):
    id: int
    plate_number: str
    zone_id: int
    entry_event_id: int
    exit_event_id: Optional[int] = None
    entry_at: datetime
    exit_at: Optional[datetime] = None
    status: ParkingSessionStatusChoices

# 6. BARRIER COMMAND
class BarrierCommandCreate(BaseModel):
    barrier_id: int
    session_id: Optional[int] = None
    event_id: Optional[int] = None
    command: BarrierCommandTypeChoices = BarrierCommandTypeChoices.OPEN
    idempotency_key: str

class BarrierCommandOut(BaseSchema):
    id: int
    barrier_id: int
    session_id: Optional[int] = None
    event_id: Optional[int] = None
    command: BarrierCommandTypeChoices
    idempotency_key: str
    status: BarrierCommandStatusChoices
    created_at: datetime
    acknowledged_at: Optional[datetime] = None

# 7. ПОДТВЕРЖДЕНИЕ ПРОЕЗДА
class PassageConfirm(BaseModel):
    event_id: int
    idempotency_key: str
    passage_source: str
    passage_confirmed_at: datetime