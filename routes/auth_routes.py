import requests
import re
import os
import secrets
import bcrypt

from PIL import Image, UnidentifiedImageError

from datetime import datetime, timezone, timedelta

from bson import ObjectId
from bson.errors import InvalidId

from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    current_app
)

from pymongo.errors import DuplicateKeyError, PyMongoError

from services.face_registration_service import face_registration_service


def create_auth_blueprint(db):

    auth = Blueprint("auth", __name__)

    voters = db["voters"]
    pending_otp = db["pending_otp"]

    # Candidate, election and participation collections
    elections = db["elections"]
    candidates = db["candidates"]
    participation = db["voter_participation"]

    pending_otp.create_index(
        "expires_at",
        expireAfterSeconds=0
    )

    pending_otp.create_index(
        "challenge_id",
        unique=True
    )

    # -----------------------------------------
    # DATABASE INDEXES
    # -----------------------------------------

    voters.create_index(
        [("email_normalized", 1)],
        unique=True,
        partialFilterExpression={
            "email_normalized": {"$type": "string"}
        }
    )

    voters.create_index(
        [("mobile", 1)],
        unique=True,
        partialFilterExpression={
            "mobile": {"$type": "string"}
        }
    )

    voters.create_index(
        [("epic_normalized", 1)],
        unique=True,
        partialFilterExpression={
            "epic_normalized": {"$type": "string"}
        }
    )

    # -----------------------------------------
    # VOTER REGISTRATION
    # -----------------------------------------

    @auth.route("/register", methods=["GET", "POST"])
    def register():

        if request.method == "POST":

            full_name = request.form.get(
                "full_name", ""
            ).strip()

            dob = request.form.get(
                "dob", ""
            ).strip()

            gender = request.form.get(
                "gender", ""
            ).strip()

            mobile = request.form.get(
                "mobile", ""
            ).strip()

            email = request.form.get(
                "email", ""
            ).strip().lower()

            epic = request.form.get(
                "epic", ""
            ).strip().upper()

            address = request.form.get(
                "address", ""
            ).strip()

            state = request.form.get(
                "state", ""
            ).strip()

            district = request.form.get(
                "district", ""
            ).strip()

            constituency = request.form.get(
                "constituency", ""
            ).strip()

            taluk = request.form.get(
                "taluk", ""
            ).strip()

            password = request.form.get(
                "password", ""
            )

            confirm_password = request.form.get(
                "confirm_password", ""
            )

            # Required fields
            if not all([
                full_name,
                dob,
                gender,
                mobile,
                email,
                epic,
                address,
                state,
                district,
                constituency,
                taluk,
                password,
                confirm_password
            ]):

                flash(
                    "Please fill all required fields.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            # Password validation
            if password != confirm_password:

                flash(
                    "Passwords do not match.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            if len(password) < 8:

                flash(
                    "Password must contain at least 8 characters.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            # Mobile validation
            if not re.fullmatch(
                r"[6-9]\d{9}",
                mobile
            ):

                flash(
                    "Enter a valid 10-digit mobile number.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            # Email validation
            if not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email
            ):

                flash(
                    "Enter a valid email address.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            # Validate and privately store Voter ID images
            front_file = request.files.get("epic_front")
            back_file = request.files.get("epic_back")

            if (
                not front_file
                or not front_file.filename
                or not back_file
                or not back_file.filename
            ):

                flash(
                    "Both Voter ID images are required.",
                    "danger"
                )

                return redirect(
                    url_for("auth.register")
                )

            allowed_extensions = current_app.config.get(
                "ALLOWED_DOCUMENT_EXTENSIONS",
                {"jpg", "jpeg", "png"}
            )

            upload_folder = current_app.config["UPLOAD_FOLDER"]

            os.makedirs(
                upload_folder,
                exist_ok=True
            )

            saved_document_paths = []
            document_names = {}

            for field_name, uploaded_file in (
                ("epic_front", front_file),
                ("epic_back", back_file)
            ):

                extension = uploaded_file.filename.rsplit(
                    ".",
                    1
                )[-1].lower()

                if extension not in allowed_extensions:

                    flash(
                        "Voter ID images must be JPG or PNG.",
                        "danger"
                    )

                    for saved_path in saved_document_paths:

                        if os.path.exists(saved_path):
                            os.remove(saved_path)

                    return redirect(
                        url_for("auth.register")
                    )

                try:

                    image = Image.open(
                        uploaded_file.stream
                    )

                    image.verify()

                    uploaded_file.stream.seek(0)

                except (
                    UnidentifiedImageError,
                    OSError,
                    ValueError
                ):

                    flash(
                        "One of the uploaded files is not a valid image.",
                        "danger"
                    )

                    for saved_path in saved_document_paths:

                        if os.path.exists(saved_path):
                            os.remove(saved_path)

                    return redirect(
                        url_for("auth.register")
                    )

                stored_name = (
                    secrets.token_hex(16)
                    + "."
                    + extension
                )

                destination = os.path.join(
                    upload_folder,
                    stored_name
                )

                uploaded_file.save(destination)

                saved_document_paths.append(destination)

                document_names[field_name] = stored_name

            # Hash password
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt()
            )

            voter_data = {

                "full_name": full_name,
                "dob": dob,
                "gender": gender,
                "mobile": mobile,
                "email": email,
                "email_normalized": email,
                "epic": epic,
                "epic_normalized": epic,
                "address": address,
                "state": state,
                "district": district,
                "constituency": constituency,
                "taluk": taluk,

                "documents": {
                    "epic_front": document_names["epic_front"],
                    "epic_back": document_names["epic_back"],
                    "verification_status": "pending",
                    "uploaded_at": datetime.now(timezone.utc)
                },

                "password": password_hash,

                "status": "pending",
                "is_verified": False,
                "has_voted": False,

                "face_embedding": None,

                "created_at": datetime.now(timezone.utc)
            }

            try:

                voters.insert_one(voter_data)

                flash(
                    "Registration successful! Wait for admin approval.",
                    "success"
                )

                return redirect(
                    url_for("auth.login")
                )

            except DuplicateKeyError:

                for saved_path in saved_document_paths:

                    if os.path.exists(saved_path):
                        os.remove(saved_path)

                flash(
                    "Email, mobile number or Voter ID already registered.",
                    "danger"
                )

            except PyMongoError:

                for saved_path in saved_document_paths:

                    if os.path.exists(saved_path):
                        os.remove(saved_path)

                current_app.logger.exception(
                    "Voter registration failed"
                )

                flash(
                    "Registration failed. Please try again.",
                    "danger"
                )

        return render_template("register.html")

    # -----------------------------------------
    # VOTER LOGIN + VOICE OTP
    # -----------------------------------------

    @auth.route("/login", methods=["GET", "POST"])
    def login():

        if request.method == "POST":

            identifier = request.form.get(
                "identifier", ""
            ).strip()

            password = request.form.get(
                "password", ""
            )

            if not identifier or not password:

                flash(
                    "Enter your login details.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            normalized = identifier.lower()
            normalized_epic = identifier.upper()

            voter = voters.find_one({
                "$or": [
                    {"email": normalized},
                    {"email_normalized": normalized},
                    {"mobile": identifier},
                    {"epic": normalized_epic},
                    {"epic_normalized": normalized_epic}
                ]
            })

            if not voter:

                flash(
                    "Invalid login details.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            stored_password = (
                voter.get("password_hash")
                or voter.get("password")
            )

            password_valid = False

            if stored_password:

                try:

                    if isinstance(stored_password, str):

                        stored_password = stored_password.encode(
                            "utf-8"
                        )

                    else:

                        stored_password = bytes(
                            stored_password
                        )

                    password_valid = bcrypt.checkpw(
                        password.encode("utf-8"),
                        stored_password
                    )

                except (ValueError, TypeError):

                    password_valid = False

            if not password_valid:

                flash(
                    "Invalid login details.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            if voter.get("status") != "approved":

                flash(
                    "Your account is not approved yet.",
                    "warning"
                )

                return redirect(
                    url_for("auth.login")
                )

            api_key = current_app.config.get(
                "TWOFACTOR_API_KEY"
            )

            if not api_key:

                current_app.logger.error(
                    "2Factor API key is not configured"
                )

                flash(
                    "OTP service is not configured. Please contact the administrator.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            mobile = str(
                voter.get("mobile", "")
            ).strip()

            mobile = re.sub(
                r"[\s+()-]",
                "",
                mobile
            )

            if len(mobile) == 10 and mobile.isdigit():

                mobile = "91" + mobile

            elif (
                len(mobile) != 12
                or not mobile.startswith("91")
                or not mobile.isdigit()
            ):

                flash(
                    "Your registered mobile number is invalid. Please contact the administrator.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            now = datetime.now(timezone.utc)

            voter_id = str(voter["_id"])

            expiry_minutes = max(
                1,
                int(
                    current_app.config.get(
                        "OTP_EXPIRY_MINUTES",
                        5
                    )
                )
            )

            resend_seconds = max(
                1,
                int(
                    current_app.config.get(
                        "OTP_RESEND_SECONDS",
                        60
                    )
                )
            )

            # Check existing OTP
            existing = pending_otp.find_one(
                {
                    "voter_id": voter_id,
                    "expires_at": {"$gt": now}
                },
                sort=[("created_at", -1)]
            )

            if existing:

                created_at = existing.get(
                    "created_at",
                    now
                )

                if (
                    now - created_at
                ).total_seconds() < resend_seconds:

                    session.clear()

                    session["otp_challenge_id"] = (
                        existing["challenge_id"]
                    )

                    return redirect(
                        url_for("auth.verify_otp")
                    )

                pending_otp.delete_one({
                    "_id": existing["_id"]
                })

            # Send OTP call
            try:

                send_url = (
                    f"https://2factor.in/API/V1/"
                    f"{api_key}/SMS/{mobile}/AUTOGEN"
                )

                response = requests.get(
                    send_url,
                    timeout=20
                )

                result = response.json()

            except (
                requests.RequestException,
                ValueError
            ):

                current_app.logger.exception(
                    "2Factor OTP send request failed"
                )

                flash(
                    "Unable to send OTP call right now. Please try again later.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            if (
                response.status_code != 200
                or result.get("Status") != "Success"
                or not result.get("Details")
            ):

                current_app.logger.error(
                    "2Factor OTP send failed: %s",
                    result.get("Details", "Unknown provider error")
                )

                flash(
                    "OTP call could not be sent. Please try again later.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            challenge_id = secrets.token_urlsafe(32)

            pending_record = {

                "challenge_id": challenge_id,
                "voter_id": voter_id,
                "provider_session_id": result["Details"],
                "created_at": now,
                "expires_at": now + timedelta(
                    minutes=expiry_minutes
                ),
                "attempts": 0
            }

            try:

                pending_otp.insert_one(
                    pending_record
                )

            except PyMongoError:

                current_app.logger.exception(
                    "Could not save pending OTP challenge"
                )

                flash(
                    "Could not start OTP verification. Please try again.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            session.clear()

            session["otp_challenge_id"] = challenge_id

            flash(
                "A verification call has been sent to your registered mobile number.",
                "success"
            )

            return redirect(
                url_for("auth.verify_otp")
            )

        return render_template("login.html")

    # -----------------------------------------
    # VERIFY VOICE OTP
    # -----------------------------------------

    @auth.route("/verify-otp", methods=["GET", "POST"])
    def verify_otp():

        challenge_id = session.get(
            "otp_challenge_id"
        )

        if not challenge_id:

            flash(
                "Please login to request an OTP.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        now = datetime.now(timezone.utc)

        challenge = pending_otp.find_one({
            "challenge_id": challenge_id
        })

        if not challenge:

            session.clear()

            flash(
                "OTP session not found or expired. Please login again.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        if challenge.get("expires_at") <= now:

            pending_otp.delete_one({
                "_id": challenge["_id"]
            })

            session.clear()

            flash(
                "OTP expired. Please login again to request a new OTP.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        max_attempts = max(
            1,
            int(
                current_app.config.get(
                    "OTP_MAX_ATTEMPTS",
                    3
                )
            )
        )

        if challenge.get("attempts", 0) >= max_attempts:

            pending_otp.delete_one({
                "_id": challenge["_id"]
            })

            session.clear()

            flash(
                "Maximum OTP attempts reached. Please login again.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        if request.method == "POST":

            otp = request.form.get(
                "otp", ""
            ).strip()

            if not re.fullmatch(r"\d{6}", otp):

                flash(
                    "Enter a valid 6-digit OTP.",
                    "danger"
                )

                return render_template(
                    "otp_verify.html"
                )

            api_key = current_app.config.get(
                "TWOFACTOR_API_KEY"
            )

            verify_url = (
                f"https://2factor.in/API/V1/{api_key}/SMS/VERIFY/"
                f"{challenge['provider_session_id']}/{otp}"
            )

            try:

                response = requests.get(
                    verify_url,
                    timeout=20
                )

                result = response.json()

            except (
                requests.RequestException,
                ValueError
            ):

                current_app.logger.exception(
                    "2Factor OTP verification request failed"
                )

                flash(
                    "Verification service is temporarily unavailable. Please try again.",
                    "danger"
                )

                return render_template(
                    "otp_verify.html"
                ), 503

            if (
                response.status_code != 200
                or result.get("Status") != "Success"
            ):

                pending_otp.update_one(
                    {"_id": challenge["_id"]},
                    {
                        "$inc": {
                            "attempts": 1
                        }
                    }
                )

                remaining = max(
                    0,
                    max_attempts
                    - challenge.get("attempts", 0)
                    - 1
                )

                if remaining == 0:

                    pending_otp.delete_one({
                        "_id": challenge["_id"]
                    })

                    session.clear()

                    flash(
                        "Maximum OTP attempts reached. Please login again.",
                        "danger"
                    )

                    return redirect(
                        url_for("auth.login")
                    )

                flash(
                    f"Incorrect OTP. Attempts remaining: {remaining}.",
                    "danger"
                )

                return render_template(
                    "otp_verify.html"
                )

            try:

                voter_id = ObjectId(
                    challenge["voter_id"]
                )

            except (InvalidId, TypeError):

                pending_otp.delete_one({
                    "_id": challenge["_id"]
                })

                session.clear()

                flash(
                    "Voter session is invalid. Please login again.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            voter = voters.find_one({
                "_id": voter_id,
                "status": "approved"
            })

            pending_otp.delete_one({
                "_id": challenge["_id"]
            })

            session.clear()

            if not voter:

                flash(
                    "Approved voter account not found.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            session["voter_id"] = str(
                voter["_id"]
            )

            session["role"] = "voter"

            session["otp_verified"] = True

            flash(
                "OTP verified. Login successful!",
                "success"
            )

            return redirect(
                url_for("auth.dashboard")
            )

        return render_template("otp_verify.html")

    # -----------------------------------------
    # VOTER DASHBOARD
    # -----------------------------------------

    @auth.route("/voter/dashboard")
    def dashboard():

        if (
            session.get("role") != "voter"
            or not session.get("otp_verified")
        ):

            flash(
                "Please complete login and OTP verification first.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        try:

            voter_id = ObjectId(
                session.get("voter_id")
            )

        except (InvalidId, TypeError):

            session.clear()

            flash(
                "Invalid session. Please login again.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        voter = voters.find_one({
            "_id": voter_id,
            "status": "approved"
        })

        if not voter:

            session.clear()

            flash(
                "Approved voter account not found.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        return render_template(
            "voter_dashboard.html",
            voter=voter
        )

    # -----------------------------------------
    # VIEW CANDIDATES - VOTER SIDE
    # -----------------------------------------

    @auth.route("/voter/candidates")
    def view_candidates():

        # Login and OTP verification check
        if (
            session.get("role") != "voter"
            or not session.get("otp_verified")
            or not session.get("voter_id")
        ):

            flash(
                "Please login and complete OTP verification first.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        # Validate voter ID
        try:

            voter_id = ObjectId(
                session["voter_id"]
            )

        except (InvalidId, TypeError):

            session.clear()

            flash(
                "Invalid session. Please login again.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        # Find approved voter
        voter = voters.find_one({
            "_id": voter_id,
            "status": "approved"
        })

        if not voter:

            session.clear()

            flash(
                "Approved voter account not found.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        try:

            # Get all non-archived elections
            election_list = list(
                elections.find({
                    "status": {
                        "$ne": "archived"
                    }
                }).sort(
                    "created_at",
                    -1
                )
            )

            now = datetime.now(timezone.utc)

            for election in election_list:

                start_at = election.get("start_at")
                end_at = election.get("end_at")

                if start_at and end_at:

                    # Handle MongoDB naive datetime values
                    if start_at.tzinfo is None:

                        start_at = start_at.replace(
                            tzinfo=timezone.utc
                        )

                    if end_at.tzinfo is None:

                        end_at = end_at.replace(
                            tzinfo=timezone.utc
                        )

                    # Calculate display status
                    if now < start_at:

                        election["display_status"] = "upcoming"

                    elif now <= end_at:

                        election["display_status"] = "active"

                    else:

                        election["display_status"] = "completed"

                else:

                    election["display_status"] = "unknown"

                # -----------------------------------------
                # CHECK WHETHER CURRENT VOTER HAS VOTED
                # -----------------------------------------

                election["already_voted"] = participation.find_one({
                    "election_id": election["_id"],
                    "voter_id": voter_id,
                    "status": "cast"
                }) is not None

                # Load candidates belonging to this election
                election["candidate_list"] = list(
                    candidates.find({
                        "election_id": election["_id"]
                    }).sort(
                        "created_at",
                        1
                    )
                )

            return render_template(
                "voter_candidates.html",
                voter=voter,
                elections=election_list
            )

        except PyMongoError:

            current_app.logger.exception(
                "Could not load voter election candidates"
            )

            flash(
                "Unable to load candidates right now. Please try again.",
                "danger"
            )

            return redirect(
                url_for("auth.dashboard")
            )

    # -----------------------------------------
    # FACE REGISTRATION FOR EXISTING VOTER
    # -----------------------------------------

    @auth.route(
        "/voter/update-face",
        methods=["POST"]
    )
    def update_face():

        # Check login session
        if (
            session.get("role") != "voter"
            or not session.get("voter_id")
            or not session.get("otp_verified")
        ):

            flash(
                "Please login first.",
                "warning"
            )

            return redirect(
                url_for("auth.login")
            )

        try:

            voter_id = ObjectId(
                session["voter_id"]
            )

        except (InvalidId, TypeError):

            session.clear()

            flash(
                "Invalid session. Please login again.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        # Find existing approved voter
        voter = voters.find_one({
            "_id": voter_id,
            "status": "approved"
        })

        if not voter:

            flash(
                "Approved voter account not found.",
                "danger"
            )

            return redirect(
                url_for("auth.login")
            )

        # Get captured image
        face_image = request.form.get(
            "face_image",
            ""
        ).strip()

        if not face_image:

            flash(
                "Please capture your face first.",
                "warning"
            )

            return redirect(
                url_for("auth.dashboard")
            )

        # Generate face embedding
        try:

            embedding = face_registration_service.generate_embedding(
                face_image
            )

        except ValueError as error:

            flash(
                str(error),
                "danger"
            )

            return redirect(
                url_for("auth.dashboard")
            )

        except RuntimeError:

            current_app.logger.exception(
                "Face registration failed"
            )

            flash(
                "Face registration failed. Please try again.",
                "danger"
            )

            return redirect(
                url_for("auth.dashboard")
            )

        # Save embedding in existing voter document
        try:

            result = voters.update_one(
                {
                    "_id": voter_id,
                    "status": "approved"
                },
                {
                    "$set": {
                        "face_embedding": embedding,
                        "face_model": "Facenet512",
                        "face_registered_at": datetime.now(timezone.utc),
                        "face_verified": False
                    }
                }
            )

            if result.matched_count == 0:

                flash(
                    "Voter account could not be updated.",
                    "danger"
                )

            else:

                flash(
                    "Face registered successfully!",
                    "success"
                )

        except PyMongoError:

            current_app.logger.exception(
                "Database face update failed"
            )

            flash(
                "Unable to save face data. Please try again.",
                "danger"
            )

        return redirect(
            url_for("auth.dashboard")
        )

    # -----------------------------------------
    # VOTER LOGOUT
    # -----------------------------------------

    @auth.route("/logout")
    def logout():

        session.clear()

        flash(
            "You have been logged out.",
            "success"
        )

        return redirect(
            url_for("auth.login")
        )

    return auth