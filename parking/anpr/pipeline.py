from PIL import Image
from parking.anpr.detector import detect_plates
from parking.anpr.recognizer import recognize_plate


def process_image(image: Image.Image) -> list[dict]:
    results = []

    for detection in detect_plates(image):
        result = recognize_plate(detection["crop"])

        results.append({
            **result,
            "yolo_confidence": detection["yolo_confidence"],
            "bbox": detection["bbox"]
        })

    return results
