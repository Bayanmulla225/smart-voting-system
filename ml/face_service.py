
import numpy as np
from deepface import DeepFace


class FaceRecognitionService:

    def __init__(self):
        self.model_name = "Facenet512"
        self.detector_backend = "opencv"
        self.distance_metric = "cosine"
        self.embedding_size = 512

        # Initial threshold; validate using your own test images.
        self.face_threshold = 0.30

    def generate_embedding(self, image):

        try:
            results = DeepFace.represent(
                img_path=image,
                model_name=self.model_name,
                detector_backend=self.detector_backend,
                enforce_detection=True
            )

            if not results:
                raise ValueError("No face detected in image.")

            if len(results) != 1:
                raise ValueError("Please capture only one face.")

            embedding = np.asarray(
                results[0]["embedding"],
                dtype=np.float32
            )

            if embedding.shape != (self.embedding_size,):
                raise ValueError("Invalid face embedding dimensions.")

            if not np.all(np.isfinite(embedding)):
                raise ValueError("Invalid face embedding values.")

            return embedding.tolist()

        except ValueError:
            raise

        except Exception as error:
            raise RuntimeError(
                f"Face embedding generation failed: {error}"
            ) from error

    def compare_embeddings(self, embedding1, embedding2):

        vector1 = np.asarray(embedding1, dtype=np.float32)
        vector2 = np.asarray(embedding2, dtype=np.float32)

        if vector1.shape != (self.embedding_size,):
            raise ValueError("Invalid registered face embedding.")

        if vector2.shape != (self.embedding_size,):
            raise ValueError("Invalid captured face embedding.")

        if not np.all(np.isfinite(vector1)) or not np.all(np.isfinite(vector2)):
            raise ValueError("Face embedding contains invalid values.")

        norm_product = (
            np.linalg.norm(vector1) * np.linalg.norm(vector2)
        )

        if norm_product == 0:
            raise ValueError("Invalid face embedding.")

        cosine_similarity = np.dot(
            vector1,
            vector2
        ) / norm_product

        cosine_distance = 1.0 - cosine_similarity

        return float(cosine_distance)

    def verify_face(self, registered_embedding, captured_embedding):

        distance = self.compare_embeddings(
            registered_embedding,
            captured_embedding
        )

        matched = distance <= self.face_threshold

        return {
            "matched": bool(matched),
            "distance": round(distance, 4),
            "threshold": self.face_threshold,
            "model": self.model_name
        }


face_service = FaceRecognitionService()
