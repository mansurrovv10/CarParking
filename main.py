from fastapi import FastAPI
import uvicorn
from parking.api import parkingZone, barrier, barrierCommand, camera, parkingSession, vihicleEvent, anpr


parking_app = FastAPI(title="Manas Airport Smart Parking — Backend MVP")

parking_app.include_router(parkingZone.zone_router)
parking_app.include_router(barrier.barrier_router)
parking_app.include_router(barrierCommand.barrier_command_router)
parking_app.include_router(camera.camera_router)
parking_app.include_router(parkingSession.session_router)
parking_app.include_router(vihicleEvent.event_router)
parking_app.include_router(vihicleEvent.passage_router)
parking_app.include_router(anpr.anpr_router)


if __name__ == "__main__":
    uvicorn.run(parking_app, host="127.0.0.1", port=8000)
