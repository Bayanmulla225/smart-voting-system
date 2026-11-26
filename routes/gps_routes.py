
from flask import Blueprint, request, jsonify, session, current_app
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError
from datetime import datetime, timezone
import math


def create_gps_blueprint(db):

    gps = Blueprint("gps", __name__, url_prefix="/gps")
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
                "message": "Invalid session. Please login again."
            }), 401)

        except PyMongoError:
            current_app.logger.exception("GPS voter lookup failed")

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

    @gps.route("/capture", methods=["POST"])
    def capture_location():

        voter, error_response = get_approved_voter()

        if error_response:
            return error_response

        data = request.get_json(silent=True) or {}

        # Require explicit user consent
        if data.get("consent") is not True:
            return jsonify({
                "success": False,
                "message": "Please provide permission to save your location."
            }), 400

        try:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
            accuracy = float(data.get("accuracy"))

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "Invalid GPS coordinates."
            }), 400

        # Validate coordinates
        if not all(map(math.isfinite, [latitude, longitude, accuracy])):
            return jsonify({
                "success": False,
                "message": "Invalid GPS values."
            }), 400

        if not -90 <= latitude <= 90:
            return jsonify({
                "success": False,
                "message": "Invalid latitude."
            }), 400

        if not -180 <= longitude <= 180:
            return jsonify({
                "success": False,
                "message": "Invalid longitude."
            }), 400

        if accuracy <= 0 or accuracy > 100000:
            return jsonify({
                "success": False,
                "message": "Invalid GPS accuracy."
            }), 400

        captured_at = datetime.now(timezone.utc)

        location_data = {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_meters": accuracy,
            "captured_at": captured_at,
            "consent": True,
            "method": "browser_geolocation"
        }

        try:
            result = voters.update_one(
                {
                    "_id": voter["_id"],
                    "status": "approved"
                },
                {
                    "$set": {
                        "location_capture": location_data
                    }
                }
            )

            if result.matched_count != 1:
                return jsonify({
                    "success": False,
                    "message": "Voter account could not be updated."
                }), 404

        except PyMongoError:
            current_app.logger.exception("GPS location save failed")

            return jsonify({
                "success": False,
                "message": "Unable to save location."
            }), 500

        return jsonify({
            "success": True,
            "message": "Location captured and saved successfully.",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_meters": accuracy,
                "captured_at": captured_at.isoformat()
            }
        }), 200

    @gps.route("/status", methods=["GET"])
    def location_status():

        voter, error_response = get_approved_voter()

        if error_response:
            return error_response

        location = voter.get("location_capture")

        if not location:
            return jsonify({
                "success": True,
                "captured": False,
                "message": "No location has been captured."
            }), 200

        captured_at = location.get("captured_at")

        return jsonify({
            "success": True,
            "captured": True,
            "location": {
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "accuracy_meters": location.get("accuracy_meters"),
                "captured_at": (
                    captured_at.isoformat()
                    if captured_at else None
                )
            }
        }), 200

    return gps
