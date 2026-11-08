from fastapi import FastAPI
import uvicorn
from parking.api.parkingZone import zone_router
from parking.api.barrier import barrier_router
from parking.api.barrierCommand import barrier_command_router
from parking.api.camera import camera_router
from parking.api.parkingSession import session_router
from parking.api.vihicleEvent import event_router, passage_router

parking_app = FastAPI(title="Manas Airport Smart Parking — Backend MVP")

parking_app.include_router(zone_router)
parking_app.include_router(barrier_router)
parking_app.include_router(barrier_command_router)
parking_app.include_router(camera_router)
parking_app.include_router(event_router)
parking_app.include_router(passage_router)
parking_app.include_router(session_router)


if __name__ == "__main__":
    uvicorn.run("main:parking_app", host="127.0.0.1", port=8000, reload=True)