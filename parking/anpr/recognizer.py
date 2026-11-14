import os
from collections import defaultdict
from functools import lru_cache
import cv2
import numpy as np
from paddleocr import TextRecognition
from PIL import Image, ImageOps

from parking.anpr.plate_parser import normalize_plate, parse_plate


@lru_cache(maxsize=1)
def get_ocr_model():
    return TextRecognition(
        model_name="PP-OCRv6_medium_rec",
        model_dir=os.getenv("ANPR_OCR_MODEL_DIR") or None,
        device="cpu"
    )


def read_text(image):
    output = get_ocr_model().predict(input=image, batch_size=1)
    if not output:
        return "", 0.0

    data = output[0].json
    data = data.get("res", data)
    return str(data.get("rec_text") or ""), float(data.get("rec_score") or 0)


def recognize_plate(image: Image.Image) -> dict:
    rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    original = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    h, w = original.shape[:2]
    enlarged = cv2.resize(original, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    enhanced = cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)

    readings = []
    matches = defaultdict(list)

    for variant in (enlarged, enhanced, original):
        raw, score = read_text(variant)
        readings.append((raw, score))

        cleaned = normalize_plate(raw)
        parsed = parse_plate(cleaned)

        if parsed and parsed["plate_number"] == cleaned and score >= 0.80:
            matches[cleaned].append(score)

    best_raw = max(readings, key=lambda item: item[1])[0]
    confirmed = [plate for plate, scores in matches.items() if len(scores) >= 2]

    if len(confirmed) == 1 and len(matches) == 1:
        plate = confirmed[0]
        parsed = parse_plate(plate)
        return {
            "plate_raw": best_raw,
            "plate_number": plate,
            "confidence": round(min(matches[plate]), 4),
            "region": parsed["region"],
            "ocr_status": "FORMAT_VALID"
        }

    return {
        "plate_raw": best_raw,
        "plate_number": None,
        "confidence": None,
        "region": None,
        "ocr_status": "CONFLICT_REVIEW" if len(matches) > 1 else "NOT_RECOGNIZED"
    }
