import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import wraps

from bson import ObjectId
from bson.errors import InvalidId

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
)

from werkzeug.utils import secure_filename


def create_election_blueprint(db):

    election_bp = Blueprint(
        "election",
        __name__,
        url_prefix="/admin/elections",
    )

    elections = db["elections"]
    votes = db["votes"]
    candidates = db["candidates"]

    ALLOWED_IMAGE_EXTENSIONS = {
        "png", "jpg", "jpeg", "webp"
    }

    MAX_IMAGE_SIZE = 5 * 1024 * 1024

    # ==========================================
    # UPLOAD FOLDER
    # ==========================================

    def get_upload_folder():

        if not current_app.static_folder:
            raise RuntimeError(
                "Flask static folder is not configured."
            )

        folder = (
            Path(current_app.static_folder)
            / "uploads"
            / "candidates"
        ).resolve()

        folder.mkdir(
            parents=True,
            exist_ok=True
        )

        return folder

    # ==========================================
    # TIMEZONE
    # ==========================================

    def get_app_timezone():

        timezone_name = os.getenv(
            "APP_TIMEZONE",
            "Asia/Kolkata"
        )

        return ZoneInfo(timezone_name)

    # ==========================================
    # ADMIN AUTHENTICATION
    # ==========================================

    def admin_required(function):

        @wraps(function)
        def wrapper(*args, **kwargs):

            if (
                session.get("role") != "admin"
                or not session.get("admin_id")
            ):

                flash(
                    "Please login as admin first.",
                    "error"
                )

                return redirect(
                    url_for("admin.login")
                )

            return function(*args, **kwargs)

        return wrapper

    # ==========================================
    # OBJECT ID
    # ==========================================

    def get_object_id(value):

        try:
            return ObjectId(value)

        except (InvalidId, TypeError):
            return None

    # ==========================================
    # DATETIME HELPERS
    # ==========================================

    def parse_local_datetime(value):

        if not value:
            raise ValueError(
                "Please enter the date and time."
            )

        try:

            local_value = datetime.strptime(
                value,
                "%Y-%m-%dT%H:%M"
            )

        except ValueError:

            raise ValueError(
                "Please enter a valid date and time."
            )

        local_value = local_value.replace(
            tzinfo=get_app_timezone()
        )

        return local_value.astimezone(
            timezone.utc
        )

    def to_local_input(value):

        if not value:
            return ""

        if value.tzinfo is None:

            value = value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            get_app_timezone()
        ).strftime("%Y-%m-%dT%H:%M")

    def calculate_status(start_at, end_at):

        now = datetime.now(timezone.utc)

        if now < start_at:
            return "upcoming"

        if now <= end_at:
            return "active"

        return "completed"

    def get_display_status(election):

        if election.get("status") == "archived":
            return "archived"

        return calculate_status(
            election["start_at"],
            election["end_at"]
        )

    # ==========================================
    # CANDIDATE IMAGE UPLOAD
    # ==========================================

    def save_candidate_image(file_storage, prefix):

        if not file_storage or not file_storage.filename:
            return None

        original_name = secure_filename(
            file_storage.filename
        )

        if not original_name or "." not in original_name:

            raise ValueError(
                "Invalid image file."
            )

        extension = original_name.rsplit(
            ".", 1
        )[1].lower()

        if extension not in ALLOWED_IMAGE_EXTENSIONS:

            raise ValueError(
                "Only JPG, JPEG, PNG and WEBP images are allowed."
            )

        file_storage.stream.seek(
            0,
            os.SEEK_END
        )

        file_size = file_storage.stream.tell()

        file_storage.stream.seek(0)

        if file_size <= 0:

            raise ValueError(
                "The selected image is empty."
            )

        if file_size > MAX_IMAGE_SIZE:

            raise ValueError(
                "Image size must not exceed 5 MB."
            )

        upload_folder = get_upload_folder()

        filename = (
            f"{prefix}_{uuid.uuid4().hex}.{extension}"
        )

        destination = upload_folder / filename

        print(
            "[CANDIDATE UPLOAD] Receiving:",
            original_name,
            flush=True
        )

        print(
            "[CANDIDATE UPLOAD] Destination:",
            destination,
            flush=True
        )

        file_storage.save(str(destination))

        if not destination.is_file():

            raise RuntimeError(
                "Image file was not created."
            )

        print(
            "[CANDIDATE UPLOAD] Saved successfully:",
            destination,
            flush=True
        )

        return f"uploads/candidates/{filename}"

    # ==========================================
    # DELETE IMAGE
    # ==========================================

    def delete_candidate_image(image_path):

        if not image_path:
            return

        try:

            upload_folder = get_upload_folder()

            filename = Path(image_path).name

            image_file = (
                upload_folder / filename
            ).resolve()

            if (
                image_file.parent == upload_folder.resolve()
                and image_file.is_file()
            ):

                image_file.unlink()

        except OSError:

            current_app.logger.exception(
                "Could not delete candidate image: %s",
                image_path
            )

    def cleanup_new_images(image_paths):

        for image_path in image_paths:
            delete_candidate_image(image_path)

    # ==========================================
    # LIST ELECTIONS
    # ==========================================

    @election_bp.route("/")
    @admin_required
    def list_elections():

        election_list = list(
            elections.find().sort(
                "created_at",
                -1
            )
        )

        for election in election_list:

            election["display_status"] = (
                get_display_status(election)
            )

        return render_template(
            "admin_elections.html",
            elections=election_list
        )

    # ==========================================
    # CREATE ELECTION
    # ==========================================

    @election_bp.route(
        "/create",
        methods=["GET", "POST"]
    )
    @admin_required
    def create_election():

        if request.method == "POST":

            try:

                title = request.form.get(
                    "title", ""
                ).strip()

                description = request.form.get(
                    "description", ""
                ).strip()

                if not title:

                    raise ValueError(
                        "Election title is required."
                    )

                start_at = parse_local_datetime(
                    request.form.get("start_at")
                )

                end_at = parse_local_datetime(
                    request.form.get("end_at")
                )

                if end_at <= start_at:

                    raise ValueError(
                        "End date must be after start date."
                    )

                now = datetime.now(timezone.utc)

                election = {
                    "title": title,
                    "description": description,
                    "start_at": start_at,
                    "end_at": end_at,
                    "status": calculate_status(
                        start_at,
                        end_at
                    ),
                    "created_at": now,
                    "updated_at": now,
                    "created_by": str(
                        session.get("admin_id")
                    )
                }

                elections.insert_one(election)

                flash(
                    "Election created successfully!",
                    "success"
                )

                return redirect(
                    url_for("election.list_elections")
                )

            except ValueError as error:

                flash(str(error), "error")

            except Exception:

                current_app.logger.exception(
                    "Election creation failed"
                )

                flash(
                    "Could not create election. Check the server terminal.",
                    "error"
                )

        return render_template(
            "admin_election_form.html",
            election=None
        )
        # ==========================================
    # EDIT ELECTION
    # ==========================================

    @election_bp.route(
        "/edit/<election_id>",
        methods=["GET", "POST"]
    )
    @admin_required
    def edit_election(election_id):

        object_id = get_object_id(election_id)

        if object_id is None:

            flash(
                "Invalid election ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if election.get("status") == "archived":

            flash(
                "Archived elections cannot be edited.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if request.method == "POST":

            try:

                if votes.count_documents({
                    "election_id": object_id
                }) > 0:

                    raise ValueError(
                        "This election already has votes and cannot be edited."
                    )

                title = request.form.get(
                    "title", ""
                ).strip()

                description = request.form.get(
                    "description", ""
                ).strip()

                if not title:

                    raise ValueError(
                        "Election title is required."
                    )

                start_at = parse_local_datetime(
                    request.form.get("start_at")
                )

                end_at = parse_local_datetime(
                    request.form.get("end_at")
                )

                if end_at <= start_at:

                    raise ValueError(
                        "End date must be after start date."
                    )

                elections.update_one(
                    {"_id": object_id},
                    {
                        "$set": {
                            "title": title,
                            "description": description,
                            "start_at": start_at,
                            "end_at": end_at,
                            "status": calculate_status(
                                start_at,
                                end_at
                            ),
                            "updated_at": datetime.now(
                                timezone.utc
                            )
                        }
                    }
                )

                flash(
                    "Election updated successfully!",
                    "success"
                )

                return redirect(
                    url_for("election.list_elections")
                )

            except ValueError as error:

                flash(str(error), "error")

            except Exception:

                current_app.logger.exception(
                    "Election update failed"
                )

                flash(
                    "Could not update election.",
                    "error"
                )

        election["start_input"] = to_local_input(
            election.get("start_at")
        )

        election["end_input"] = to_local_input(
            election.get("end_at")
        )

        return render_template(
            "admin_election_form.html",
            election=election
        )

    # ==========================================
    # DELETE ELECTION
    # ==========================================

    @election_bp.route(
        "/delete/<election_id>",
        methods=["POST"]
    )
    @admin_required
    def delete_election(election_id):

        object_id = get_object_id(election_id)

        if object_id is None:

            flash(
                "Invalid election ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if votes.count_documents({
            "election_id": object_id
        }) > 0:

            flash(
                "This election has votes and cannot be deleted. Archive it instead.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        candidate_list = list(
            candidates.find({
                "election_id": object_id
            })
        )

        elections.delete_one({
            "_id": object_id
        })

        candidates.delete_many({
            "election_id": object_id
        })

        for candidate in candidate_list:

            delete_candidate_image(
                candidate.get("candidate_photo")
            )

            delete_candidate_image(
                candidate.get("party_symbol_image")
            )

        flash(
            "Election deleted successfully.",
            "success"
        )

        return redirect(
            url_for("election.list_elections")
        )

    # ==========================================
    # ARCHIVE ELECTION
    # ==========================================

    @election_bp.route(
        "/archive/<election_id>",
        methods=["POST"]
    )
    @admin_required
    def archive_election(election_id):

        object_id = get_object_id(election_id)

        if object_id is None:

            flash(
                "Invalid election ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        result = elections.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "status": "archived",
                    "archived_at": datetime.now(
                        timezone.utc
                    ),
                    "archived_by": str(
                        session.get("admin_id")
                    ),
                    "updated_at": datetime.now(
                        timezone.utc
                    )
                }
            }
        )

        if result.matched_count == 0:

            flash(
                "Election not found.",
                "error"
            )

        else:

            flash(
                "Election archived successfully.",
                "success"
            )

        return redirect(
            url_for("election.list_elections")
        )

    # ==========================================
    # LIST CANDIDATES
    # ==========================================

    @election_bp.route(
        "/<election_id>/candidates"
    )
    @admin_required
    def list_candidates(election_id):

        object_id = get_object_id(election_id)

        if object_id is None:

            flash(
                "Invalid election ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        candidate_list = list(
            candidates.find({
                "election_id": object_id
            }).sort(
                "created_at",
                -1
            )
        )

        return render_template(
            "admin_candidates.html",
            election=election,
            candidates=candidate_list
        )

    # ==========================================
    # ADD CANDIDATE
    # ==========================================

    @election_bp.route(
        "/<election_id>/candidates/add",
        methods=["GET", "POST"]
    )
    @admin_required
    def add_candidate(election_id):

        object_id = get_object_id(election_id)

        if object_id is None:

            flash(
                "Invalid election ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if election.get("status") == "archived":

            flash(
                "Cannot add candidates to an archived election.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if request.method == "POST":

            saved_images = []

            try:

                print(
                    "\n========== CANDIDATE ADD UPLOAD DEBUG ==========",
                    flush=True
                )

                print(
                    "ADD CANDIDATE ROUTE REACHED",
                    flush=True
                )

                print(
                    "REQUEST METHOD:",
                    request.method,
                    flush=True
                )

                print(
                    "CONTENT TYPE:",
                    request.content_type,
                    flush=True
                )

                print(
                    "CONTENT LENGTH:",
                    request.content_length,
                    flush=True
                )

                print(
                    "FILES RECEIVED:",
                    list(request.files.keys()),
                    flush=True
                )

                for field_name in (
                    "candidate_photo",
                    "party_symbol_image"
                ):

                    uploaded_file = request.files.get(
                        field_name
                    )

                    if uploaded_file and uploaded_file.filename:

                        print(
                            field_name,
                            "FILE NAME:",
                            uploaded_file.filename,
                            flush=True
                        )

                    else:

                        print(
                            field_name,
                            "NOT RECEIVED",
                            flush=True
                        )

                print(
                    "================================================\n",
                    flush=True
                )

                name = request.form.get(
                    "name", ""
                ).strip()

                party = request.form.get(
                    "party", ""
                ).strip()

                constituency = request.form.get(
                    "constituency", ""
                ).strip()

                symbol = request.form.get(
                    "symbol", ""
                ).strip()

                description = request.form.get(
                    "description", ""
                ).strip()

                if not name:

                    raise ValueError(
                        "Candidate name is required."
                    )

                if not party:

                    raise ValueError(
                        "Party name is required."
                    )

                if not constituency:

                    raise ValueError(
                        "Constituency is required."
                    )

                candidate_photo = save_candidate_image(
                    request.files.get("candidate_photo"),
                    "candidate"
                )

                if candidate_photo:
                    saved_images.append(candidate_photo)

                party_symbol_image = save_candidate_image(
                    request.files.get("party_symbol_image"),
                    "symbol"
                )

                if party_symbol_image:
                    saved_images.append(party_symbol_image)

                now = datetime.now(timezone.utc)

                candidate_document = {
                    "election_id": object_id,
                    "name": name,
                    "party": party,
                    "constituency": constituency,
                    "symbol": symbol,
                    "description": description,
                    "candidate_photo": candidate_photo,
                    "party_symbol_image": party_symbol_image,
                    "created_at": now,
                    "updated_at": now
                }

                candidates.insert_one(
                    candidate_document
                )

                flash(
                    "Candidate added successfully!",
                    "success"
                )

                return redirect(
                    url_for(
                        "election.list_candidates",
                        election_id=election_id
                    )
                )

            except ValueError as error:

                cleanup_new_images(saved_images)

                flash(
                    str(error),
                    "error"
                )

            except Exception as error:

                cleanup_new_images(saved_images)

                print(
                    "[CANDIDATE ADD ERROR]",
                    repr(error),
                    flush=True
                )

                current_app.logger.exception(
                    "Candidate creation failed"
                )

                flash(
                    "Could not add candidate. Check the server terminal.",
                    "error"
                )

        return render_template(
            "admin_candidate_form.html",
            election=election,
            candidate=None
        )
        # ==========================================
    # EDIT CANDIDATE
    # ==========================================

    @election_bp.route(
        "/<election_id>/candidates/edit/<candidate_id>",
        methods=["GET", "POST"]
    )
    @admin_required
    def edit_candidate(election_id, candidate_id):

        election_object_id = get_object_id(
            election_id
        )

        candidate_object_id = get_object_id(
            candidate_id
        )

        if (
            election_object_id is None
            or candidate_object_id is None
        ):

            flash(
                "Invalid election or candidate ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": election_object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if election.get("status") == "archived":

            flash(
                "Archived election candidates cannot be edited.",
                "error"
            )

            return redirect(
                url_for(
                    "election.list_candidates",
                    election_id=election_id
                )
            )

        candidate = candidates.find_one({
            "_id": candidate_object_id,
            "election_id": election_object_id
        })

        if not candidate:

            flash(
                "Candidate not found.",
                "error"
            )

            return redirect(
                url_for(
                    "election.list_candidates",
                    election_id=election_id
                )
            )

        if request.method == "POST":

            saved_images = []

            try:

                print(
                    "\n========== CANDIDATE EDIT UPLOAD DEBUG ==========",
                    flush=True
                )

                print(
                    "EDIT CANDIDATE ROUTE REACHED",
                    flush=True
                )

                print(
                    "REQUEST METHOD:",
                    request.method,
                    flush=True
                )

                print(
                    "CONTENT TYPE:",
                    request.content_type,
                    flush=True
                )

                print(
                    "CONTENT LENGTH:",
                    request.content_length,
                    flush=True
                )

                print(
                    "FILES RECEIVED:",
                    list(request.files.keys()),
                    flush=True
                )

                for field_name in (
                    "candidate_photo",
                    "party_symbol_image"
                ):

                    uploaded_file = request.files.get(
                        field_name
                    )

                    if uploaded_file and uploaded_file.filename:

                        print(
                            field_name,
                            "FILE NAME:",
                            uploaded_file.filename,
                            flush=True
                        )

                    else:

                        print(
                            field_name,
                            "NOT RECEIVED",
                            flush=True
                        )

                print(
                    "=================================================\n",
                    flush=True
                )

                name = request.form.get(
                    "name", ""
                ).strip()

                party = request.form.get(
                    "party", ""
                ).strip()

                constituency = request.form.get(
                    "constituency", ""
                ).strip()

                symbol = request.form.get(
                    "symbol", ""
                ).strip()

                description = request.form.get(
                    "description", ""
                ).strip()

                if not name:

                    raise ValueError(
                        "Candidate name is required."
                    )

                if not party:

                    raise ValueError(
                        "Party name is required."
                    )

                if not constituency:

                    raise ValueError(
                        "Constituency is required."
                    )

                new_photo = save_candidate_image(
                    request.files.get("candidate_photo"),
                    "candidate"
                )

                if new_photo:
                    saved_images.append(new_photo)

                new_symbol_image = save_candidate_image(
                    request.files.get("party_symbol_image"),
                    "symbol"
                )

                if new_symbol_image:
                    saved_images.append(new_symbol_image)

                updated_data = {
                    "name": name,
                    "party": party,
                    "constituency": constituency,
                    "symbol": symbol,
                    "description": description,
                    "updated_at": datetime.now(
                        timezone.utc
                    )
                }

                if new_photo:
                    updated_data["candidate_photo"] = new_photo

                if new_symbol_image:
                    updated_data["party_symbol_image"] = new_symbol_image

                result = candidates.update_one(
                    {
                        "_id": candidate_object_id,
                        "election_id": election_object_id
                    },
                    {
                        "$set": updated_data
                    }
                )

                if result.matched_count != 1:

                    raise RuntimeError(
                        "Candidate record was not found during update."
                    )

                # Delete old images only after MongoDB update succeeds.
                if new_photo:

                    delete_candidate_image(
                        candidate.get("candidate_photo")
                    )

                if new_symbol_image:

                    delete_candidate_image(
                        candidate.get("party_symbol_image")
                    )

                current_app.logger.info(
                    "Candidate updated. New photo=%s, new symbol=%s",
                    new_photo,
                    new_symbol_image
                )

                flash(
                    "Candidate updated successfully!",
                    "success"
                )

                return redirect(
                    url_for(
                        "election.list_candidates",
                        election_id=election_id
                    )
                )

            except ValueError as error:

                cleanup_new_images(saved_images)

                flash(
                    str(error),
                    "error"
                )

            except Exception as error:

                cleanup_new_images(saved_images)

                print(
                    "[CANDIDATE UPDATE ERROR]",
                    repr(error),
                    flush=True
                )

                current_app.logger.exception(
                    "Candidate update failed"
                )

                flash(
                    "Could not update candidate. Check the server terminal.",
                    "error"
                )

        return render_template(
            "admin_candidate_form.html",
            election=election,
            candidate=candidate
        )
        # ==========================================
    # DELETE CANDIDATE
    # ==========================================

    @election_bp.route(
        "/<election_id>/candidates/delete/<candidate_id>",
        methods=["POST"]
    )
    @admin_required
    def delete_candidate(election_id, candidate_id):

        election_object_id = get_object_id(
            election_id
        )

        candidate_object_id = get_object_id(
            candidate_id
        )

        if (
            election_object_id is None
            or candidate_object_id is None
        ):

            flash(
                "Invalid election or candidate ID.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        election = elections.find_one({
            "_id": election_object_id
        })

        if not election:

            flash(
                "Election not found.",
                "error"
            )

            return redirect(
                url_for("election.list_elections")
            )

        if election.get("status") == "archived":

            flash(
                "Candidates of an archived election cannot be deleted.",
                "error"
            )

            return redirect(
                url_for(
                    "election.list_candidates",
                    election_id=election_id
                )
            )

        candidate = candidates.find_one({
            "_id": candidate_object_id,
            "election_id": election_object_id
        })

        if not candidate:

            flash(
                "Candidate not found.",
                "error"
            )

            return redirect(
                url_for(
                    "election.list_candidates",
                    election_id=election_id
                )
            )

        existing_votes = votes.count_documents({
            "election_id": election_object_id,
            "candidate_id": candidate_object_id
        })

        if existing_votes > 0:

            flash(
                "This candidate already has votes and cannot be deleted.",
                "error"
            )

            return redirect(
                url_for(
                    "election.list_candidates",
                    election_id=election_id
                )
            )

        result = candidates.delete_one({
            "_id": candidate_object_id,
            "election_id": election_object_id
        })

        if result.deleted_count == 1:

            delete_candidate_image(
                candidate.get("candidate_photo")
            )

            delete_candidate_image(
                candidate.get("party_symbol_image")
            )

            flash(
                "Candidate deleted successfully!",
                "success"
            )

        else:

            flash(
                "Candidate could not be deleted.",
                "error"
            )

        return redirect(
            url_for(
                "election.list_candidates",
                election_id=election_id
            )
        )

    return election_bp