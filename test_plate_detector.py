from ultralytics import YOLO
import cv2

MODEL_PATH = "app/models/plate_detector/license-plate-finetune-v1s.pt"
IMAGE_PATH = "test.jpg"  # любой кадр с въездной камеры

model = YOLO(MODEL_PATH)

img = cv2.imread(IMAGE_PATH)
assert img is not None, "Не удалось загрузить изображение"

results = model.predict(
    source=img,
    conf=0.25,
    imgsz=640,
    verbose=True
)

r = results[0]

if r.boxes is None:
    print("❌ Номеров не найдено")
else:
    print(f"✅ Найдено номеров: {len(r.boxes)}")
    for b in r.boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        conf = float(b.conf[0])
        print("bbox:", x1, y1, x2, y2, "conf:", conf)

        cv2.rectangle(img, (x1,y1), (x2,y2), (0,255,0), 2)

    cv2.imshow("plates", img)
    cv2.waitKey(0)
