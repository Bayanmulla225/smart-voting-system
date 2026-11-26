
import cv2
import mediapipe as mp
import numpy as np
import random

from ml.anti_spoofing.anti_spoof_service import AntiSpoofService


class LivenessService:

    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh

        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=2,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )

        self.anti_spoof = AntiSpoofService()

        self.challenges = [
            "BLINK",
            "TURN_LEFT",
            "TURN_RIGHT"
        ]

        random.shuffle(self.challenges)

        self.current_challenge = 0
        self.blink_closed = False

        # Final straight-face confirmation
        self.returning_to_center = False
        self.center_frames = 0
        self.required_center_frames = 5

        self.completed = False

        print("Liveness Detection Service Loaded!")

    def detect_faces(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return None

        if len(results.multi_face_landmarks) > 1:
            return "MULTIPLE"

        return results.multi_face_landmarks[0].landmark

    def get_eye_ratio(self, landmarks, indexes):
        points = [
            np.array([landmarks[i].x, landmarks[i].y])
            for i in indexes
        ]

        vertical1 = np.linalg.norm(points[1] - points[5])
        vertical2 = np.linalg.norm(points[2] - points[4])
        horizontal = np.linalg.norm(points[0] - points[3])

        if horizontal == 0:
            return 0

        return (vertical1 + vertical2) / (2.0 * horizontal)

    def check_blink(self, landmarks):
        left_eye = [33, 160, 158, 133, 153, 144]
        right_eye = [362, 385, 387, 263, 373, 380]

        left_ratio = self.get_eye_ratio(landmarks, left_eye)
        right_ratio = self.get_eye_ratio(landmarks, right_eye)

        ear = (left_ratio + right_ratio) / 2

        if ear < 0.20:
            self.blink_closed = True

        elif self.blink_closed and ear > 0.24:
            self.blink_closed = False
            return True

        return False

    def check_head_direction(self, landmarks):
        nose_x = landmarks[1].x
        left_eye_x = landmarks[33].x
        right_eye_x = landmarks[263].x

        eye_center = (left_eye_x + right_eye_x) / 2
        face_width = abs(right_eye_x - left_eye_x)

        if face_width == 0:
            return "CENTER"

        offset = (nose_x - eye_center) / face_width

        if offset < -0.18:
            return "LEFT"

        if offset > 0.18:
            return "RIGHT"

        return "CENTER"

    def reset(self):
        self.challenges = [
            "BLINK",
            "TURN_LEFT",
            "TURN_RIGHT"
        ]

        random.shuffle(self.challenges)

        self.current_challenge = 0
        self.blink_closed = False

        self.returning_to_center = False
        self.center_frames = 0

        self.completed = False

    def check_frame(self, frame):

        # Step 1: Anti-spoofing check
        anti_result = self.anti_spoof.check_frame(frame)

        if anti_result is None:
            return {
                "status": "NO_FACE",
                "message": "Please face the camera."
            }

        if anti_result.get("status") == "MULTIPLE_FACES":
            return {
                "status": "MULTIPLE_FACES",
                "message": "Only one person should be visible."
            }

        prediction = anti_result.get("prediction")

        if prediction is None:
            return {
                "status": "SPOOF_CHECK_PENDING",
                "message": "Checking face authenticity."
            }

        anti_status = prediction.get("status")
        confidence = prediction.get("confidence", 0)

        # Step 2: Reject spoof
        if anti_status != "REAL":
            return {
                "status": "SPOOF_DETECTED",
                "message": "Spoof detected. Use your live face.",
                "confidence": round(confidence, 4)
            }

        # Step 3: Face mesh detection
        landmarks = self.detect_faces(frame)

        if landmarks is None:
            if self.returning_to_center:
                self.center_frames = 0

            return {
                "status": "NO_FACE",
                "message": "Please face the camera."
            }

        if isinstance(landmarks, str):
            return {
                "status": "MULTIPLE_FACES",
                "message": "Only one person should be visible."
            }

        direction = self.check_head_direction(landmarks)

        # Step 4: Already verified
        if self.completed:
            return {
                "status": "LIVE_VERIFIED",
                "message": "Liveness verification completed.",
                "anti_spoof": "REAL",
                "confidence": round(confidence, 4)
            }

        # Step 5: Final straight-face confirmation
        if self.returning_to_center:

            if direction == "CENTER":
                self.center_frames += 1
            else:
                self.center_frames = 0

            if self.center_frames >= self.required_center_frames:
                self.completed = True

                return {
                    "status": "LIVE_VERIFIED",
                    "message": "Liveness verified. Face is centered.",
                    "anti_spoof": "REAL",
                    "confidence": round(confidence, 4),
                    "center_frames": self.center_frames
                }

            return {
                "status": "RETURN_CENTER",
                "message": "Please look straight at the camera and hold still.",
                "center_frames": self.center_frames,
                "required_center_frames": self.required_center_frames,
                "completed_challenges": len(self.challenges),
                "total_challenges": len(self.challenges),
                "anti_spoof": "REAL",
                "confidence": round(confidence, 4)
            }

        # Step 6: Current random challenge
        challenge = self.challenges[self.current_challenge]
        passed = False

        if challenge == "BLINK":
            passed = self.check_blink(landmarks)
            message = "Please blink your eyes."

        elif challenge == "TURN_LEFT":
            passed = direction == "LEFT"
            message = "Please turn your head left."

        elif challenge == "TURN_RIGHT":
            passed = direction == "RIGHT"
            message = "Please turn your head right."

        # Step 7: Update challenge progress
        if passed:
            self.current_challenge += 1
            self.blink_closed = False

            if self.current_challenge >= len(self.challenges):
                self.returning_to_center = True
                self.center_frames = 0

                return {
                    "status": "RETURN_CENTER",
                    "message": "Challenges completed. Please look straight at the camera.",
                    "center_frames": 0,
                    "required_center_frames": self.required_center_frames,
                    "completed_challenges": len(self.challenges),
                    "total_challenges": len(self.challenges),
                    "anti_spoof": "REAL",
                    "confidence": round(confidence, 4)
                }

            next_challenge = self.challenges[self.current_challenge]
            message = "Good! Next challenge: " + next_challenge

        return {
            "status": "CHALLENGE",
            "message": message,
            "challenge": challenge,
            "completed_challenges": self.current_challenge,
            "total_challenges": len(self.challenges),
            "anti_spoof": "REAL",
            "confidence": round(confidence, 4)
        }

    def close(self):
        self.face_mesh.close()
        self.anti_spoof.close()


if __name__ == "__main__":

    camera = cv2.VideoCapture(0)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    service = LivenessService()

    if not camera.isOpened():
        print("Camera not available!")
        service.close()
        raise SystemExit(1)

    print("Combined Liveness Detection Started.")
    print("Press Q to exit.")

    try:
        while True:
            success, frame = camera.read()

            if not success:
                break

            result = service.check_frame(frame)
            status = result["status"]

            color = (0, 255, 0)

            if status in [
                "NO_FACE",
                "MULTIPLE_FACES",
                "SPOOF_DETECTED"
            ]:
                color = (0, 0, 255)

            elif status == "SPOOF_CHECK_PENDING":
                color = (0, 255, 255)

            cv2.putText(
                frame,
                result["message"],
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2
            )

            cv2.putText(
                frame,
                "Status: " + status,
                (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2
            )

            cv2.imshow(
                "SmartVote Combined Liveness Detection",
                frame
            )

            if status == "LIVE_VERIFIED":
                print("SUCCESS:", result)
                cv2.waitKey(1000)
                break

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        service.close()
        cv2.destroyAllWindows()
