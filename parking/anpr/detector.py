from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageOps
from ultralytics import YOLO


MODEL_PATH = Path(__file__).resolve().parent / "weights" / "best.pt"


@lru_cache(maxsize=1)
def get_detector() -> YOLO:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Модель не найдена: {MODEL_PATH}")
    return YOLO(str(MODEL_PATH))


def detect_plates(image: Image.Image) -> list[dict]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size

    results = get_detector().predict(image, imgsz=960, conf=0.25, verbose=False)
    detections = []

    for box in results[0].boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

        pad_x = max(4, int((x2 - x1) * 0.10))
        pad_y = max(3, int((y2 - y1) * 0.06))

        left = max(0, x1 - pad_x)
        top = max(0, y1 - pad_y)
        right = min(width, x2 + pad_x + 1)
        bottom = min(height, y2 + pad_y + 1)

        if right <= left or bottom <= top:
            continue

        detections.append({
            "crop": image.crop((left, top, right, bottom)),
            "bbox": [left, top, right, bottom],
            "yolo_confidence": round(float(box.conf[0]), 4)
        })

    return sorted(detections, key=lambda x: x["yolo_confidence"], reverse=True)
