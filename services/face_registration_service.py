
import base64
import binascii

import cv2
import numpy as np

from deepface import DeepFace


class FaceRegistrationService:

    def __init__(self):
        self.model_name = "Facenet512"
        self.detector_backend = "opencv"
        self.embedding_size = 512

    def decode_image(self, image_data):

        if not image_data or not isinstance(image_data, str):
            raise ValueError("Face image is required.")

        if "," not in image_data:
            raise ValueError("Invalid image format.")

        header, encoded_image = image_data.split(",", 1)

        if header not in (
            "data:image/jpeg;base64",
            "data:image/jpg;base64",
            "data:image/png;base64"
        ):
            raise ValueError("Only JPEG and PNG images are allowed.")

        try:
            image_bytes = base64.b64decode(
                encoded_image,
                validate=True
            )
        except binascii.Error as error:
            raise ValueError("Invalid image encoding.") from error

        if len(image_bytes) > 5 * 1024 * 1024:
            raise ValueError("Image size must be below 5 MB.")

        image_array = np.frombuffer(
            image_bytes,
            dtype=np.uint8
        )

        image = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if image is None:
            raise ValueError("Unable to read captured image.")

        height, width = image.shape[:2]

        if width < 100 or height < 100:
            raise ValueError("Image resolution is too small.")

        return image

    def enhance_image(self, image):

        # Improve brightness and contrast without changing color channels.
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)

        lightness, a_channel, b_channel = cv2.split(lab)

        clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        )

        enhanced_lightness = clahe.apply(lightness)

        enhanced_lab = cv2.merge((
            enhanced_lightness,
            a_channel,
            b_channel
        ))

        enhanced = cv2.cvtColor(
            enhanced_lab,
            cv2.COLOR_LAB2BGR
        )

        return enhanced

    def represent_face(self, image):

        results = DeepFace.represent(
            img_path=image,
            model_name=self.model_name,
            detector_backend=self.detector_backend,
            enforce_detection=True
        )

        if not results:
            raise ValueError("No face detected.")

        if len(results) != 1:
            raise ValueError("Only one face should be visible.")

        embedding = results[0].get("embedding")

        if embedding is None:
            raise ValueError("Unable to generate face embedding.")

        embedding = np.asarray(
            embedding,
            dtype=np.float32
        )

        if embedding.shape != (self.embedding_size,):
            raise ValueError("Invalid face embedding dimensions.")

        if not np.all(np.isfinite(embedding)):
            raise ValueError("Invalid face embedding values.")

        return embedding.tolist()

    def generate_embedding(self, image_data):

        image = self.decode_image(image_data)

        # First attempt: original camera image.
        try:
            return self.represent_face(image)

        except ValueError as original_error:

            if "Only one face" in str(original_error):
                raise

            # Second attempt: improve brightness and contrast.
            try:
                enhanced = self.enhance_image(image)

                return self.represent_face(enhanced)

            except ValueError as enhanced_error:
                raise ValueError(
                    "Face could not be detected. "
                    "Please face the camera directly, improve lighting "
                    "and capture again. "
                    f"Detection details: {enhanced_error}"
                ) from enhanced_error

            except Exception as error:
                raise RuntimeError(
                    f"Face processing failed: {error}"
                ) from error

        except Exception as error:
            raise RuntimeError(
                f"Face processing failed: {error}"
            ) from error


face_registration_service = FaceRegistrationService()
