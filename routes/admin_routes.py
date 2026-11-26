import os
import bcrypt

from datetime import datetime, timezone
from functools import wraps

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    send_file,
    abort,
)


def create_admin_blueprint(db):

    admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

    admins = db["admins"]
    voters = db["voters"]
    elections = db["elections"]
    candidates = db["candidates"]
    votes = db["votes"]

    # ------------------------------------------
    # HELPERS
    # ------------------------------------------

    def admin_required(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            if session.get("role") != "admin" or not session.get("admin_id"):
                flash("Please login as administrator first.", "warning")
                return redirect(url_for("admin.login"))

            return func(*args, **kwargs)

        return wrapper

    def normalize(value):
        return " ".join(
            str(value or "").strip().casefold().split()
        )

    def get_election_status(election):

        if election.get("status") == "archived":
            return "archived"

        start_at = election.get("start_at")
        end_at = election.get("end_at")

        if not start_at or not end_at:
            return "unknown"

        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)

        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        if now < start_at:
            return "upcoming"

        if now <= end_at:
            return "active"

        return "completed"

    # ------------------------------------------
    # ADMIN LOGIN
    # ------------------------------------------

    @admin_bp.route("/login", methods=["GET", "POST"])
    def login():

        if session.get("role") == "admin":
            return redirect(url_for("admin.dashboard"))

        if request.method == "POST":

            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            admin = admins.find_one({"email": email})

            if admin and bcrypt.checkpw(
                password.encode("utf-8"),
                bytes(admin["password_hash"])
            ):

                session.clear()
                session["admin_id"] = str(admin["_id"])
                session["admin_email"] = admin["email"]
                session["role"] = "admin"

                flash("Admin login successful!", "success")
                return redirect(url_for("admin.dashboard"))

            flash("Invalid admin email or password.", "danger")

        return render_template("admin_login.html")

    # ------------------------------------------
    # ADMIN DASHBOARD + VOTING STATISTICS
    # ------------------------------------------

    @admin_bp.route("/dashboard")
    @admin_required
    def dashboard():

        try:
            # VOTER STATISTICS
            total_voters = voters.count_documents({})
            pending_voters = voters.count_documents({
                "status": "pending"
            })
            approved_voters = voters.count_documents({
                "status": "approved"
            })
            rejected_voters = voters.count_documents({
                "status": "rejected"
            })

            pending_list = list(
                voters.find({"status": "pending"})
                .sort("created_at", -1)
            )

            approved_list = list(
                voters.find({"status": "approved"})
                .sort("created_at", -1)
            )

            # OVERALL VOTING STATISTICS
            total_elections = elections.count_documents({})
            total_votes = votes.count_documents({})

            active_elections = 0
            upcoming_elections = 0
            completed_elections = 0

            election_documents = list(
                elections.find().sort("created_at", -1)
            )

            election_stats = []

            for election in election_documents:

                election_id = election["_id"]
                election_status = get_election_status(election)

                if election_status == "active":
                    active_elections += 1
                elif election_status == "upcoming":
                    upcoming_elections += 1
                elif election_status == "completed":
                    completed_elections += 1

                # Get candidates for this election.
                election_candidates = list(
                    candidates.find({
                        "election_id": election_id
                    }).sort("created_at", 1)
                )

                # Count votes for each candidate.
                candidate_vote_counts = list(
                    votes.aggregate([
                        {
                            "$match": {
                                "election_id": election_id
                            }
                        },
                        {
                            "$group": {
                                "_id": "$candidate_id",
                                "vote_count": {"$sum": 1}
                            }
                        }
                    ])
                )

                vote_count_map = {
                    str(item["_id"]): item["vote_count"]
                    for item in candidate_vote_counts
                }

                candidate_results = []

                for candidate in election_candidates:

                    candidate_id = str(candidate["_id"])

                    candidate_results.append({
                        "name": candidate.get("name", "Unknown"),
                        "party": candidate.get("party", "N/A"),
                        "symbol": candidate.get("symbol", ""),
                        "constituency": candidate.get(
                            "constituency", "N/A"
                        ),
                        "votes": vote_count_map.get(candidate_id, 0)
                    })

                election_total_votes = votes.count_documents({
                    "election_id": election_id
                })

                # Calculate eligible voters based on constituencies
                # represented by candidates in this election.
                election_constituencies = {
                    normalize(candidate.get("constituency"))
                    for candidate in election_candidates
                    if normalize(candidate.get("constituency"))
                }

                eligible_voters = 0

                if election_constituencies:

                    approved_election_voters = voters.find({
                        "status": "approved"
                    })

                    for voter in approved_election_voters:

                        voter_constituency = normalize(
                            voter.get("constituency")
                        )

                        if voter_constituency in election_constituencies:
                            eligible_voters += 1

                remaining_voters = max(
                    eligible_voters - election_total_votes,
                    0
                )

                if eligible_voters > 0:
                    voting_percentage = round(
                        (election_total_votes / eligible_voters) * 100,
                        2
                    )
                else:
                    voting_percentage = 0

                election_stats.append({
                    "id": str(election_id),
                    "title": election.get("title", "Untitled Election"),
                    "status": election_status,
                    "total_votes": election_total_votes,
                    "eligible_voters": eligible_voters,
                    "remaining_voters": remaining_voters,
                    "voting_percentage": voting_percentage,
                    "candidates": candidate_results
                })

            # OVERALL PARTICIPATION
            total_eligible_voters = sum(
                item["eligible_voters"]
                for item in election_stats
            )

            total_remaining_voters = sum(
                item["remaining_voters"]
                for item in election_stats
            )

            if total_eligible_voters > 0:
                overall_voting_percentage = round(
                    (
                        sum(item["total_votes"] for item in election_stats)
                        / total_eligible_voters
                    ) * 100,
                    2
                )
            else:
                overall_voting_percentage = 0

            return render_template(
                "admin_dashboard.html",

                # Existing voter dashboard variables
                total_voters=total_voters,
                pending_voters=pending_voters,
                approved_voters=approved_voters,
                rejected_voters=rejected_voters,
                pending_list=pending_list,
                approved_list=approved_list,

                # New election and voting statistics
                total_elections=total_elections,
                total_votes=total_votes,
                active_elections=active_elections,
                upcoming_elections=upcoming_elections,
                completed_elections=completed_elections,
                election_stats=election_stats,
                total_eligible_voters=total_eligible_voters,
                total_remaining_voters=total_remaining_voters,
                overall_voting_percentage=overall_voting_percentage
            )

        except PyMongoError:

            current_app.logger.exception(
                "Admin dashboard database error"
            )

            flash(
                "Unable to load dashboard statistics. Please try again.",
                "danger"
            )

            return redirect(url_for("admin.login"))

        except Exception:

            current_app.logger.exception(
                "Unexpected admin dashboard error"
            )

            flash(
                "An error occurred while loading the dashboard.",
                "danger"
            )

            return redirect(url_for("admin.login"))

    # ------------------------------------------
    # APPROVE VOTER
    # ------------------------------------------

    @admin_bp.route("/approve/<voter_id>", methods=["POST"])
    @admin_required
    def approve_voter(voter_id):

        try:
            result = voters.update_one(
                {
                    "_id": ObjectId(voter_id),
                    "status": "pending"
                },
                {
                    "$set": {
                        "status": "approved",
                        "is_verified": True,
                        "approved_at": datetime.now(timezone.utc),
                        "approved_by": session["admin_email"]
                    }
                }
            )

            if result.modified_count:
                flash("Voter approved successfully!", "success")
            else:
                flash(
                    "Voter not found or already processed.",
                    "warning"
                )

        except (InvalidId, PyMongoError):

            current_app.logger.exception("Voter approval failed")
            flash("Unable to approve voter.", "danger")

        return redirect(url_for("admin.dashboard"))

    # ------------------------------------------
    # REJECT VOTER
    # ------------------------------------------

    @admin_bp.route("/reject/<voter_id>", methods=["POST"])
    @admin_required
    def reject_voter(voter_id):

        try:
            result = voters.update_one(
                {
                    "_id": ObjectId(voter_id),
                    "status": "pending"
                },
                {
                    "$set": {
                        "status": "rejected",
                        "rejected_at": datetime.now(timezone.utc),
                        "rejected_by": session["admin_email"]
                    }
                }
            )

            if result.modified_count:
                flash("Voter registration rejected.", "success")
            else:
                flash(
                    "Voter not found or already processed.",
                    "warning"
                )

        except (InvalidId, PyMongoError):

            current_app.logger.exception("Voter rejection failed")
            flash("Unable to reject voter.", "danger")

        return redirect(url_for("admin.dashboard"))

    # ------------------------------------------
    # DELETE VOTER
    # ------------------------------------------

    @admin_bp.route("/delete-voter/<voter_id>", methods=["POST"])
    @admin_required
    def delete_voter(voter_id):

        try:
            voter_object_id = ObjectId(voter_id)
            voter = voters.find_one({"_id": voter_object_id})

            if not voter:
                flash("Voter record not found.", "warning")
                return redirect(url_for("admin.dashboard"))

            # Never delete a voter who has already voted.
            if voter.get("has_voted") is True:
                flash(
                    "This voter has already voted. Deletion is not allowed.",
                    "danger"
                )
                return redirect(url_for("admin.dashboard"))

            # Also check the participation collection.
            has_participated = db["voter_participation"].find_one({
                "voter_id": voter_object_id,
                "status": "cast"
            })

            if has_participated:
                flash(
                    "This voter has already voted. Deletion is not allowed.",
                    "danger"
                )
                return redirect(url_for("admin.dashboard"))

            result = voters.delete_one({
                "_id": voter_object_id
            })

            if result.deleted_count == 1:

                documents = voter.get("documents", {})
                upload_folder = current_app.config["UPLOAD_FOLDER"]

                for field in ("epic_front", "epic_back"):

                    stored_name = documents.get(field)

                    if (
                        stored_name
                        and os.path.basename(stored_name) == stored_name
                    ):

                        file_path = os.path.join(
                            upload_folder,
                            stored_name
                        )

                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)

                        except OSError:

                            current_app.logger.exception(
                                "Unable to remove voter document: %s",
                                stored_name
                            )

                flash(
                    "Voter deleted successfully. Registration can be done again.",
                    "success"
                )

            else:
                flash("Voter could not be deleted.", "warning")

        except InvalidId:
            flash("Invalid voter ID.", "danger")

        except PyMongoError:

            current_app.logger.exception("Voter deletion failed")

            flash(
                "Database error. Voter could not be deleted.",
                "danger"
            )

        return redirect(url_for("admin.dashboard"))

    # ------------------------------------------
    # VOTER DETAILS
    # ------------------------------------------

    @admin_bp.route("/voter-details/<voter_id>")
    @admin_required
    def voter_details(voter_id):

        try:
            voter = voters.find_one({
                "_id": ObjectId(voter_id)
            })

        except (InvalidId, PyMongoError):
            abort(404)

        if not voter:
            abort(404)

        return render_template(
            "admin_voter_details.html",
            voter=voter
        )

    # ------------------------------------------
    # VIEW VOTER DOCUMENT
    # ------------------------------------------

    @admin_bp.route("/voter-document/<voter_id>/<side>")
    @admin_required
    def view_voter_document(voter_id, side):

        document_fields = {
            "front": "epic_front",
            "back": "epic_back"
        }

        if side not in document_fields:
            abort(404)

        try:
            voter = voters.find_one({
                "_id": ObjectId(voter_id)
            })

        except (InvalidId, PyMongoError):
            abort(404)

        if not voter:
            abort(404)

        documents = voter.get("documents", {})
        stored_name = documents.get(document_fields[side])

        if (
            not stored_name
            or os.path.basename(stored_name) != stored_name
        ):
            abort(404)

        upload_folder = current_app.config["UPLOAD_FOLDER"]
        file_path = os.path.join(upload_folder, stored_name)

        if not os.path.isfile(file_path):
            abort(404)

        return send_file(
            file_path,
            mimetype=(
                "image/jpeg"
                if stored_name.lower().endswith((".jpg", ".jpeg"))
                else "image/png"
            ),
            as_attachment=False,
            download_name=stored_name,
            conditional=True
        )

    # ------------------------------------------
    # ADMIN LOGOUT
    # ------------------------------------------

    @admin_bp.route("/logout")
    @admin_required
    def logout():

        session.clear()

        flash("Admin logged out successfully.", "success")

        return redirect(url_for("admin.login"))

    return admin_bp


# ------------------------------------------
# CREATE INITIAL ADMIN
# ------------------------------------------

def ensure_admin(db):

    admins = db["admins"]

    email = os.getenv(
        "ADMIN_EMAIL",
        "admin@smartvote.local"
    ).strip().lower()

    password = os.getenv("ADMIN_PASSWORD", "")

    if not password:
        raise RuntimeError(
            "ADMIN_PASSWORD is missing from your .env file."
        )

    if len(password.encode("utf-8")) > 72:
        raise RuntimeError(
            "ADMIN_PASSWORD must not exceed 72 bytes."
        )

    existing_admin = admins.find_one({
        "email": email
    })

    if existing_admin:
        print("Admin account already exists.")
        return

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    )

    admins.insert_one({
        "email": email,
        "password_hash": password_hash,
        "role": "admin",
        "created_at": datetime.now(timezone.utc)
    })

    print("Initial admin account created successfully.")