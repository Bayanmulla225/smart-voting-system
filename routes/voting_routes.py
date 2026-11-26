
from datetime import datetime, timezone
import secrets
import time

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError, PyMongoError

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


def create_voting_blueprint(db):

    voting_bp = Blueprint("voting", __name__)

    voters = db["voters"]
    elections = db["elections"]
    candidates = db["candidates"]
    votes = db["votes"]
    participation = db["voter_participation"]

    # One participation record per voter per election.
    participation.create_index(
        [("election_id", 1), ("voter_id", 1)],
        unique=True,
        name="unique_voter_election"
    )

    # Anonymous ballot records must have unique ballot references.
    votes.create_index(
        [("ballot_ref", 1)],
        unique=True,
        name="unique_ballot_ref"
    )

    def normalize(value):
        return " ".join(str(value or "").strip().casefold().split())

    def get_voter():
        if (
            session.get("role") != "voter"
            or not session.get("otp_verified")
            or not session.get("voter_id")
        ):
            return None

        try:
            voter_id = ObjectId(session["voter_id"])
        except (InvalidId, TypeError):
            return None

        voter = voters.find_one({
            "_id": voter_id,
            "status": "approved"
        })

        return voter

    def get_active_election(election_id):
        try:
            object_id = ObjectId(election_id)
        except (InvalidId, TypeError):
            return None

        election = elections.find_one({"_id": object_id})

        if not election or election.get("status") == "archived":
            return None

        start_at = election.get("start_at")
        end_at = election.get("end_at")

        if not start_at or not end_at:
            return None

        # MongoDB may return naive UTC datetimes depending on configuration.
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)

        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        if not (start_at <= now <= end_at):
            return None

        return election

    def face_verification_is_valid(voter_id):
        if not session.get("face_verified"):
            return False

        if session.get("face_verified_voter") != str(voter_id):
            return False

        verified_at = session.get("face_verified_at")

        if not isinstance(verified_at, (int, float)):
            return False

        age = time.time() - verified_at

        return 0 <= age <= 300

    @voting_bp.route("/voter/vote/<election_id>", methods=["GET", "POST"])
    def vote_page(election_id):

        voter = get_voter()

        if not voter:
            flash("Please login with an approved voter account.", "warning")
            return redirect(url_for("auth.login"))

        election = get_active_election(election_id)

        if not election:
            flash("This election is not currently active.", "warning")
            return redirect(url_for("auth.voter_candidates"))

        election_object_id = election["_id"]
        voter_id = voter["_id"]

        already_voted = participation.find_one({
            "election_id": election_object_id,
            "voter_id": voter_id
        }) is not None

        voter_constituency = normalize(voter.get("constituency"))

        candidate_list = [
            candidate
            for candidate in candidates.find({
                "election_id": election_object_id
            }).sort("created_at", 1)
            if normalize(candidate.get("constituency")) == voter_constituency
        ]

        if request.method == "POST":

            if already_voted:
                flash("You have already voted in this election.", "warning")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            if not face_verification_is_valid(voter_id):
                session.pop("face_verified", None)
                session.pop("face_verified_voter", None)
                session.pop("face_verified_at", None)

                flash(
                    "Please complete face verification again before voting.",
                    "warning"
                )
                return redirect(url_for("voting.vote_page", election_id=election_id))

            candidate_id_value = request.form.get("candidate_id", "").strip()

            try:
                candidate_id = ObjectId(candidate_id_value)
            except (InvalidId, TypeError):
                flash("Please select a valid candidate.", "danger")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            selected_candidate = candidates.find_one({
                "_id": candidate_id,
                "election_id": election_object_id
            })

            if (
                not selected_candidate
                or normalize(selected_candidate.get("constituency")) != voter_constituency
            ):
                flash("Invalid candidate selection for your constituency.", "danger")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            # Recheck election status immediately before accepting the vote.
            election = get_active_election(election_id)

            if not election:
                flash("The election is no longer active.", "warning")
                return redirect(url_for("auth.voter_candidates"))

            now = datetime.now(timezone.utc)
            ballot_ref = secrets.token_urlsafe(32)

            # Keep voter identity and candidate choice in separate collections.
            # The participation record deliberately does not contain candidate_id.
            try:
                participation.insert_one({
                    "election_id": election_object_id,
                    "voter_id": voter_id,
                    "ballot_ref": ballot_ref,
                    "cast_at": now,
                    "status": "pending"
                })

            except DuplicateKeyError:
                flash("You have already voted in this election.", "warning")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            except PyMongoError:
                current_app.logger.exception("Could not create voter participation record")
                flash("Vote could not be submitted. Please try again.", "danger")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            try:
                votes.insert_one({
                    "ballot_ref": ballot_ref,
                    "election_id": election_object_id,
                    "candidate_id": candidate_id,
                    "created_at": now
                })

                participation.update_one(
                    {
                        "election_id": election_object_id,
                        "voter_id": voter_id,
                        "ballot_ref": ballot_ref
                    },
                    {"$set": {"status": "cast"}}
                )

            except Exception:
                current_app.logger.exception("Anonymous ballot insertion failed")

                # Best-effort rollback for this local academic prototype.
                participation.delete_one({
                    "election_id": election_object_id,
                    "voter_id": voter_id,
                    "ballot_ref": ballot_ref
                })

                votes.delete_one({"ballot_ref": ballot_ref})

                flash("Vote could not be saved. Please try again.", "danger")
                return redirect(url_for("voting.vote_page", election_id=election_id))

            # Require fresh face verification for any later voting attempt.
            session.pop("face_verified", None)
            session.pop("face_verified_voter", None)
            session.pop("face_verified_at", None)

            return redirect(url_for("voting.vote_success"))

        return render_template(
            "voter_vote.html",
            voter=voter,
            election=election,
            candidates=candidate_list,
            already_voted=already_voted,
            face_verified=face_verification_is_valid(voter_id)
        )

    @voting_bp.route("/voter/vote-success")
    def vote_success():

        if not get_voter():
            flash("Please login first.", "warning")
            return redirect(url_for("auth.login"))

        return render_template("vote_success.html")
    
    return voting_bp
