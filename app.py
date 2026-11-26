
from pathlib import Path

from flask import Flask, render_template, jsonify
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from flask_wtf.csrf import CSRFProtect

from config import Config

from routes.auth_routes import create_auth_blueprint
from routes.admin_routes import create_admin_blueprint, ensure_admin
from routes.face_routes import create_face_blueprint
from routes.liveness_routes import create_liveness_blueprint
from routes.gps_routes import create_gps_blueprint
from routes.election_routes import create_election_blueprint
from routes.voting_routes import create_voting_blueprint


BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    template_folder=str(BASE_DIR / "templates")
)

app.config.from_object(Config)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,

    # Maximum request upload size: 10 MB
    MAX_CONTENT_LENGTH=10 * 1024 * 1024
)

# Ensure candidate image upload directory exists
UPLOAD_FOLDER = (
    Path(app.static_folder)
    / "uploads"
    / "candidates"
)

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

csrf = CSRFProtect(app)

# MongoDB connection
mongo_client = MongoClient(
    app.config["MONGO_URI"],
    serverSelectionTimeoutMS=3000,
    tz_aware=True
)

db = mongo_client[app.config["MONGO_DB"]]


# ==========================================
# REGISTER BLUEPRINTS
# ==========================================

auth_blueprint = create_auth_blueprint(db)
app.register_blueprint(auth_blueprint)

ensure_admin(db)

admin_blueprint = create_admin_blueprint(db)
app.register_blueprint(admin_blueprint)

face_blueprint = create_face_blueprint(db)
app.register_blueprint(face_blueprint)

liveness_blueprint = create_liveness_blueprint(db)
app.register_blueprint(liveness_blueprint)

gps_blueprint = create_gps_blueprint(db)
app.register_blueprint(gps_blueprint)

election_blueprint = create_election_blueprint(db)
app.register_blueprint(election_blueprint)

app.register_blueprint(create_voting_blueprint(db))


# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================
# HEALTH CHECK
# ==========================================

@app.route("/health")
def health():

    try:

        mongo_client.admin.command("ping")

        return jsonify({
            "status": "success",
            "application": "Smart Voting System",
            "database": "connected"
        }), 200

    except PyMongoError:

        app.logger.exception(
            "MongoDB health check failed"
        )

        return jsonify({
            "status": "error",
            "application": "Smart Voting System",
            "database": "disconnected"
        }), 503


# ==========================================
# UPLOAD ERROR HANDLER
# ==========================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "status": "error",
        "message": "Uploaded files are too large. Maximum request size is 10 MB."
    }), 413


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=False
    )
