import re
from functools import lru_cache

import cv2
import easyocr
import numpy as np
from PIL import Image, ImageOps

from parking.anpr.plate_parser import parse_plate, normalize_plate


CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
REGION_PATTERN = re.compile(r"^(0[1-9]|10|11)$")
BODY_PATTERN = re.compile(r"^\d{3}[A-Z]{3}$")


@lru_cache(maxsize=1)
def get_ocr_model():
    return easyocr.Reader(["en"], gpu=False, verbose=False)


def read_text(image: np.ndarray, chars: str = CHARS):
    detections = get_ocr_model().readtext(
        image, detail=1, paragraph=False,
        allowlist=chars, decoder="beamsearch", beamWidth=5
    )

    detections.sort(key=lambda x: min(p[0] for p in x[0]))
    texts = [text for _, text, _ in detections if text.strip()]
    scores = [float(score) for _, text, score in detections if text.strip()]

    return texts, round(min(scores), 4) if scores else None


def recognize_plate(image: Image.Image) -> dict:
    image = ImageOps.exif_transpose(image).convert("RGB")
    original = np.asarray(image)

    scale = min(3.0, max(1.0, 900 / image.width))
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))

    enlarged = cv2.resize(
        original, (width, height), interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
    enhanced = cv2.createCLAHE(
        clipLimit=2.0, tileGridSize=(8, 8)
    ).apply(gray)

    variants = [original, enlarged, enhanced]
    best_raw, best_confidence = "", None
    best_score = (-1, -1.0)

    for variant in variants:
        texts, confidence = read_text(variant)
        raw = " ".join(texts)
        parsed = parse_plate(texts)

        if parsed:
            return {
                "plate_raw": raw,
                "plate_number": parsed["plate_number"],
                "confidence": confidence,
                "region": parsed["region"]
            }

        score = (len(normalize_plate(raw)), confidence or 0)
        if score > best_score:
            best_raw, best_confidence = raw, confidence
            best_score = score

        body = next(
            (normalize_plate(t) for t in texts
             if BODY_PATTERN.fullmatch(normalize_plate(t))),
            None
        )

        if body:
            left = variant[:, :max(1, int(variant.shape[1] * 0.30))]
            regions, region_conf = read_text(left, "0123456789")

            for region in regions:
                code = normalize_plate(region)

                if REGION_PATTERN.fullmatch(code):
                    parsed = parse_plate([code, body])

                    if parsed:
                        return {
                            "plate_raw": raw,
                            "plate_number": parsed["plate_number"],
                            "confidence": min(
                                confidence or 0, region_conf or 0
                            ),
                            "region": parsed["region"]
                        }

    return {
        "plate_raw": best_raw,
        "plate_number": None,
        "confidence": best_confidence,
        "region": None
    }
