
import sys
from collections import Counter, deque
import cv2
from PIL import Image
from parking.anpr.pipeline import process_image

CAMERA_SOURCE = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else (sys.argv[1] if len(sys.argv) > 1 else 0)
CONFIDENCE_THRESHOLD = 0.75
FRAME_COUNT = 5
MIN_MATCHES = 3

def main():
    cap = cv2.VideoCapture(CAMERA_SOURCE)
    if not cap.isOpened():
        raise RuntimeError(f"Камера ачылган жок: {CAMERA_SOURCE}")

    history = deque(maxlen=FRAME_COUNT)
    stable_plate, current_plate = None, None
    print("CAMERA STARTED | Press Q to exit")

    try:
        while True:
            success, frame = cap.read()
            if not success:
                print("Камерадан кадр алынган жок")
                break

            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            results = process_image(image)
            candidates = [r for r in results if r.get("plate_number")]
            best = max(candidates, key=lambda r: float(r.get("confidence") or 0)) if candidates else None

            current_plate = best["plate_number"] if best else None
            confidence = float(best.get("confidence") or 0) if best else 0.0
            history.append(current_plate if confidence >= CONFIDENCE_THRESHOLD else None)

            counts = Counter(p for p in history if p)
            plate, matches = counts.most_common(1)[0] if counts else (None, 0)
            stable_plate = plate if len(history) == FRAME_COUNT and matches >= MIN_MATCHES else None

            if best:
                x1, y1, x2, y2 = map(int, best["bbox"])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                print(f"OCR: {current_plate} | CONF: {confidence:.4f} | MATCHES: {matches}/{FRAME_COUNT}")
            else:
                print("OCR: номер табылган жок")

            text = f"STABLE: {stable_plate}" if stable_plate else f"READING: {current_plate or 'NONE'}"
            color = (0, 255, 0) if stable_plate else (0, 255, 255)
            cv2.putText(frame, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("MANAS AIRPORT - LIVE ANPR", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("CAMERA STOPPED")

if __name__ == "__main__":
    main()
