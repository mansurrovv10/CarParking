
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import cv2
from dotenv import load_dotenv
from PIL import Image

from parking.anpr.pipeline import process_image


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CAMERA_URL = os.environ["ANPR_BARRIER_CAMERA_URL"]
CAMERA_ID = int(os.environ["ANPR_BARRIER_CAMERA_ID"])
API_KEY = os.environ["ANPR_API_KEY"]
API_URL = os.getenv("ANPR_API_URL", "http://127.0.0.1:8000")

FRAME_STEP = 10
REQUIRED_VOTES = 3
COOLDOWN = 120


def send_event(result: dict, event_key: str) -> dict:
    payload = {
        "event_key": event_key,
        "camera_id": CAMERA_ID,
        "plate_raw": result["plate_raw"],
        "plate_number": result["plate_number"],
        "confidence": result["confidence"],
        "detected_at": datetime.now(timezone.utc).isoformat()
    }

    request = Request(
        f"{API_URL.rstrip('/')}/events/recognize",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-ANPR-Key": API_KEY},
        method="POST"
    )

    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    votes = deque(maxlen=REQUIRED_VOTES)
    last_sent = {}

    capture = None
    frame_count = 0
    missing = 0
    armed = True
    pending_key = None
    pending_plate = None

    try:
        while True:
            if capture is None:
                capture = cv2.VideoCapture(CAMERA_URL)

                if not capture.isOpened():
                    print("Camera offline. Reconnecting...")
                    capture.release()
                    capture = None
                    time.sleep(2)
                    continue

                votes.clear()
                missing = 0
                armed = True
                pending_key = None
                pending_plate = None
                print("Barrier camera connected")

            ok, frame = capture.read()

            if not ok:
                print("Stream lost. Reconnecting...")
                capture.release()
                capture = None
                votes.clear()
                time.sleep(2)
                continue

            frame_count += 1
            if frame_count % FRAME_STEP != 0:
                continue

            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            results = process_image(image)

            if not results:
                missing += 1
                votes.clear()

                if missing >= 5:
                    armed = True
                    pending_key = None
                    pending_plate = None

                continue

            missing = 0

            if len(results) != 1:
                votes.clear()
                continue

            result = results[0]
            plate = result.get("plate_number")

            trusted = (
                result.get("ocr_status") == "FORMAT_VALID"
                and plate is not None
                and (result.get("confidence") or 0) >= 0.85
                and result.get("yolo_confidence", 0) >= 0.80
            )

            if not trusted:
                votes.clear()
                continue

            votes.append(plate)
            print(f"PLATE={plate} | VOTES={list(votes)}")

            if len(votes) < REQUIRED_VOTES or len(set(votes)) != 1 or not armed:
                continue

            if time.monotonic() - last_sent.get(plate, float("-inf")) < COOLDOWN:
                continue

            if pending_plate != plate:
                pending_plate = plate
                pending_key = uuid4().hex

            try:
                response = send_event(result, pending_key)
                print(f"EVENT={response.get('decision')} | PLATE={plate}")

                last_sent[plate] = time.monotonic()
                armed = False
                pending_key = None
                pending_plate = None

            except Exception as error:
                print(f"API ERROR: {error}")
                time.sleep(2)

    except KeyboardInterrupt:
        print("Barrier camera stopped")

    finally:
        if capture is not None:
            capture.release()


if __name__ == "__main__":
    main()
