
import time

from flask import Blueprint, request, jsonify, session, current_app
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from ml.face_service import face_service
from services.face_registration_service import face_registration_service
from services.liveness_session_store import liveness_store


FACE_VERIFICATION_TIMEOUT = 300  # 5 minutes


def create_face_blueprint(db):
    face = Blueprint("face", __name__, url_prefix="/face")
    voters = db["voters"]

    @face.route("/verify", methods=["POST"])
    def verify_face():

        if session.get("role") != "voter" or not session.get("voter_id"):
            return jsonify({
                "success": False,
                "message": "Please login first."
            }), 401

        try:
            voter_id = ObjectId(session["voter_id"])

        except (InvalidId, TypeError):
            session.clear()

            return jsonify({
                "success": False,
                "message": "Invalid session. Please login again."
            }), 401

        # Clear any previous face verification before a new attempt.
        session.pop("face_verified", None)
        session.pop("face_verified_voter", None)
        session.pop("face_verified_at", None)

        try:
            voter = voters.find_one({
                "_id": voter_id,
                "status": "approved"
            })

        except PyMongoError:
            current_app.logger.exception("Voter lookup failed")

            return jsonify({
                "success": False,
                "message": "Database error."
            }), 500

        if not voter:
            return jsonify({
                "success": False,
                "message": "Approved voter account not found."
            }), 404

        registered_embedding = voter.get("face_embedding")

        if not registered_embedding:
            return jsonify({
                "success": False,
                "message": "Face is not registered."
            }), 400

        if voter.get("face_model") != "Facenet512":
            return jsonify({
                "success": False,
                "message": "Registered face model is not supported."
            }), 400

        token = session.get("liveness_token")

        if not token or not liveness_store.is_verified(token):
            return jsonify({
                "success": False,
                "matched": False,
                "message": "Complete liveness verification first."
            }), 403

        data = request.get_json(silent=True) or {}
        face_image = data.get("face_image", "")

        if not isinstance(face_image, str) or not face_image.strip():
            return jsonify({
                "success": False,
                "message": "Please capture your face."
            }), 400

        try:
            captured_embedding = (
                face_registration_service.generate_embedding(face_image)
            )

        except ValueError as error:
            return jsonify({
                "success": False,
                "message": str(error)
            }), 400

        except RuntimeError:
            current_app.logger.exception(
                "Face verification embedding generation failed"
            )

            return jsonify({
                "success": False,
                "message": "Unable to process face. Please try again."
            }), 500

        try:
            result = face_service.verify_face(
                registered_embedding,
                captured_embedding
            )

        except ValueError as error:
            return jsonify({
                "success": False,
                "message": str(error)
            }), 400

        except Exception:
            current_app.logger.exception("Face comparison failed")

            return jsonify({
                "success": False,
                "message": "Face comparison failed."
            }), 500

        if result["matched"]:

            if not liveness_store.consume(token):
                return jsonify({
                    "success": False,
                    "matched": False,
                    "message": "Liveness verification expired. Please try again."
                }), 403

            session.pop("liveness_token", None)

            # Create a voter-specific, time-limited verification record.
            session["face_verified"] = True
            session["face_verified_voter"] = str(voter_id)
            session["face_verified_at"] = int(time.time())
            session.modified = True

            return jsonify({
                "success": True,
                "matched": True,
                "message": "Face and liveness verified successfully.",
                "distance": result["distance"],
                "threshold": result["threshold"],
                "verification_validity_seconds": FACE_VERIFICATION_TIMEOUT
            }), 200

        return jsonify({
            "success": False,
            "matched": False,
            "message": "Face does not match the registered voter.",
            "distance": result["distance"],
            "threshold": result["threshold"]
        }), 403

    return face
