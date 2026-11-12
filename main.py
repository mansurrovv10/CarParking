from fastapi import FastAPI
import uvicorn
from parking.api import parkingZone, barrier, barrierCommand, camera, parkingSession, vihicleEvent, anpr
from parking.database.db import engine, Base
from parking.database import models
import os
from fastapi.middleware.cors import CORSMiddleware
from cors import get_allowed_origins


Base.metadata.create_all(bind=engine)

parking_app = FastAPI(title="Manas Airport Smart Parking — Backend MVP")


parking_app.add_middleware(CORSMiddleware,
    allow_origins=get_allowed_origins(os.getenv("CORS_ALLOWED_ORIGINS")),
    allow_credentials=False,
    allow_methods=["GET","POST","PATCH","OPTIONS"],
    allow_headers=["Accept","Authorization","Content-Type","X-ANPR-Key",],max_age=600)


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