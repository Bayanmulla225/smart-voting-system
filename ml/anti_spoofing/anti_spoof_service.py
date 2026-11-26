
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort


class AntiSpoofService:

    def __init__(self):
        model_path = (
            Path(__file__).parent
            / "weights"
            / "MiniFASNetV2.onnx"
        )

        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"]
        )

        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        self.face_detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.6
        )

        self.frame_count = 0
        self.cached_result = None

        print("Anti-Spoofing model loaded!")

    def predict(self, frame, bbox):

        x, y, w, h = bbox
        img_h, img_w = frame.shape[:2]

        scale = 2.7
        center_x = x + w / 2
        center_y = y + h / 2

        crop_w = w * scale
        crop_h = h * scale

        x1 = max(0, int(center_x - crop_w / 2))
        y1 = max(0, int(center_y - crop_h / 2))
        x2 = min(img_w, int(center_x + crop_w / 2))
        y2 = min(img_h, int(center_y + crop_h / 2))

        face = frame[y1:y2, x1:x2]

        if face.size == 0:
            return None

        face = cv2.resize(face, (80, 80))

        # BGR input, float32, without /255 normalization
        tensor = face.astype(np.float32)
        tensor = np.transpose(tensor, (2, 0, 1))
        tensor = np.expand_dims(tensor, axis=0)

        output = self.session.run(
            [self.output_name],
            {self.input_name: tensor}
        )[0]

        exp_values = np.exp(
            output - np.max(output, axis=1, keepdims=True)
        )

        probabilities = (
            exp_values / np.sum(exp_values, axis=1, keepdims=True)
        )[0]

        class_index = int(np.argmax(probabilities))

        # Official model mapping: class 1 = Real
        status = "REAL" if class_index == 1 else "FAKE"

        return {
            "status": status,
            "confidence": float(probabilities[class_index]),
            "scores": probabilities.tolist()
        }

    def check_frame(self, frame):

        self.frame_count += 1

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_detector.process(rgb)

        if not results.detections:
            self.cached_result = None
            return None

        if len(results.detections) > 1:
            self.cached_result = None
            return {"status": "MULTIPLE_FACES"}

        detection = results.detections[0]
        box = detection.location_data.relative_bounding_box

        h, w = frame.shape[:2]

        x = max(0, int(box.xmin * w))
        y = max(0, int(box.ymin * h))
        bw = min(w - x, int(box.width * w))
        bh = min(h - y, int(box.height * h))

        bbox = (x, y, bw, bh)

        # Run expensive ONNX inference every 5 frames.
        if self.frame_count % 5 == 0 or self.cached_result is None:
            self.cached_result = self.predict(frame, bbox)

        return {
            "bbox": bbox,
            "prediction": self.cached_result
        }

    def close(self):
        self.face_detector.close()


def main():

    service = AntiSpoofService()

    camera = cv2.VideoCapture(0)

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not camera.isOpened():
        print("Camera not available!")
        service.close()
        return

    print("Camera started. Press Q to exit.")

    try:
        while True:

            success, frame = camera.read()

            if not success:
                break

            result = service.check_frame(frame)

            if result is None:
                cv2.putText(
                    frame,
                    "No face detected",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

            elif result.get("status") == "MULTIPLE_FACES":
                cv2.putText(
                    frame,
                    "Multiple faces detected!",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

            else:
                x, y, w, h = result["bbox"]
                prediction = result["prediction"]

                if prediction is not None:
                    status = prediction["status"]
                    confidence = prediction["confidence"]

                    color = (
                        (0, 255, 0)
                        if status == "REAL"
                        else (0, 0, 255)
                    )

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        color,
                        2
                    )

                    cv2.putText(
                        frame,
                        f"{status}: {confidence:.2f}",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        color,
                        2
                    )

            cv2.imshow("SmartVote Anti-Spoofing", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        service.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
