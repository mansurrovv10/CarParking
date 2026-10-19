from fastapi import FastAPI
import uvicorn

parking_app = FastAPI(title="Parking")


if __name__ == "__main__":
    uvicorn.run(parking_app, host="127.0.0.0", port=8000)