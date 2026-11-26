
import base64
import binascii
import secrets
import time

import cv2
import numpy as np

from flask import Blueprint, request, jsonify, session, current_app
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from ml.liveness_service import LivenessService
from services.liveness_session_store import liveness_store


def create_liveness_blueprint(db):

    liveness = Blueprint("liveness", __name__, url_prefix="/liveness")
    voters = db["voters"]

    def get_approved_voter():
        if session.get("role") != "voter" or not session.get("voter_id"):
            return None, (jsonify({
                "success": False,
                "message": "Please login first."
            }), 401)

        try:
            voter_id = ObjectId(session["voter_id"])
            voter = voters.find_one({
                "_id": voter_id,
                "status": "approved"
            })
        except (InvalidId, TypeError):
            session.clear()
            return None, (jsonify({
                "success": False,
                "message": "Invalid session. Login again."
            }), 401)
        except PyMongoError:
            current_app.logger.exception("Liveness voter lookup failed")
            return None, (jsonify({
                "success": False,
                "message": "Database error."
            }), 500)

        if not voter:
            return None, (jsonify({
                "success": False,
                "message": "Approved voter account not found."
            }), 404)

        return voter, None

    def get_session_token():
        token = session.get("liveness_token")

        if not token:
            token = secrets.token_urlsafe(32)
            session["liveness_token"] = token

        return token

    @liveness.route("/start", methods=["POST"])
    def start_liveness():

        voter, error_response = get_approved_voter()
        if error_response:
            return error_response

        if not voter.get("face_embedding"):
            return jsonify({
                "success": False,
                "message": "Please register your face first."
            }), 400

        token = get_session_token()

        try:
            service = LivenessService()
            liveness_store.create(token, service)

            return jsonify({
                "success": True,
                "message": "Liveness session started.",
                "status": "STARTED"
            }), 200

        except Exception:
            current_app.logger.exception("Unable to start liveness service")
            liveness_store.remove(token)

            return jsonify({
                "success": False,
                "message": "Unable to start liveness detection."
            }), 500

    @liveness.route("/check", methods=["POST"])
    def check_liveness():

        voter, error_response = get_approved_voter()
        if error_response:
            return error_response

        token = session.get("liveness_token")
        entry = liveness_store.get(token) if token else None

        if not entry:
            return jsonify({
                "success": False,
                "message": "Liveness session expired. Start again.",
                "status": "SESSION_EXPIRED"
            }), 400

        if entry["verified"]:
            return jsonify({
                "success": True,
                "verified": True,
                "status": "LIVE_VERIFIED",
                "message": "Liveness already verified."
            }), 200

        data = request.get_json(silent=True) or {}
        image_data = data.get("frame", "")

        if not isinstance(image_data, str) or not image_data:
            return jsonify({
                "success": False,
                "message": "Camera frame is missing."
            }), 400

        if len(image_data) > 5 * 1024 * 1024:
            return jsonify({
                "success": False,
                "message": "Image is too large."
            }), 413

        try:
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]

            image_bytes = base64.b64decode(
                image_data,
                validate=True
            )

            if len(image_bytes) > 3 * 1024 * 1024:
                raise ValueError("Image is too large.")

            image_array = np.frombuffer(
                image_bytes,
                dtype=np.uint8
            )

            frame = cv2.imdecode(
                image_array,
                cv2.IMREAD_COLOR
            )

            if frame is None:
                raise ValueError("Invalid camera image.")

            height, width = frame.shape[:2]

            if width > 1280 or height > 1280:
                raise ValueError("Camera frame dimensions are too large.")

        except (ValueError, binascii.Error):
            return jsonify({
                "success": False,
                "message": "Invalid camera frame."
            }), 400

        try:
            result = entry["service"].check_frame(frame)

            if result.get("status") == "LIVE_VERIFIED":
                liveness_store.mark_verified(token)

            return jsonify({
                "success": True,
                "verified": result.get("status") == "LIVE_VERIFIED",
                **result
            }), 200

        except Exception:
            current_app.logger.exception("Liveness frame processing failed")

            liveness_store.remove(token)
            session.pop("liveness_token", None)

            return jsonify({
                "success": False,
                "message": "Liveness processing failed. Please restart.",
                "status": "ERROR"
            }), 500

    @liveness.route("/status", methods=["GET"])
    def liveness_status():

        _, error_response = get_approved_voter()
        if error_response:
            return error_response

        token = session.get("liveness_token")

        return jsonify({
            "success": True,
            "verified": liveness_store.is_verified(token) if token else False
        }), 200

    @liveness.route("/stop", methods=["POST"])
    def stop_liveness():

        _, error_response = get_approved_voter()
        if error_response:
            return error_response

        token = session.pop("liveness_token", None)

        if token:
            liveness_store.remove(token)

        return jsonify({
            "success": True,
            "message": "Liveness session stopped."
        }), 200

    return liveness
