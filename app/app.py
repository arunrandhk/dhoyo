import logging

from flask import Flask, jsonify, request, redirect
from social import social
from arena import arena
from messages import messages
from friends import friends
from organisations import organisations
from progression import progression
from reminders import reminders
from play_games import play_games
from db import (
    initialize_database,
    test_database_connection,
    create_user,
    get_users,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
import os
app.config["AUTH_COOKIE_SECURE"] = os.environ.get("AUTH_COOKIE_SECURE") == "1"
app.register_blueprint(social)
app.register_blueprint(arena)
app.register_blueprint(messages)
app.register_blueprint(friends)
app.register_blueprint(organisations)
app.register_blueprint(progression)
app.register_blueprint(reminders)
app.register_blueprint(play_games)
from auth import install_auth, render_terminates_tls, secure_transport
install_auth(app)


@app.before_request
def protect_sign_in_page():
    if request.path in ('/ring', '/sportspace', '/static/sportspace/index.html') and not secure_transport():
        return 'Open this page over HTTPS to sign in.', 403


@app.after_request
def fresh_frontend(response):
    if request.path.startswith(("/static/", "/api/")):
        response.headers["Cache-Control"] = "no-store"
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' https://accounts.google.com/gsi/client; "
        "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; "
        "img-src 'self' data: https:; connect-src 'self' https://accounts.google.com/gsi/; "
        "frame-src https://accounts.google.com/gsi/; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.path in ('/ring', '/sportspace', '/static/sportspace/index.html'):
        from google_auth import client_id
        if client_id():
            # GIS validates the authorised browser origin. Keep API and emailed
            # acknowledgement pages on the stricter no-referrer policy.
            response.headers['Referrer-Policy'] = ('strict-origin-when-cross-origin'
                if request.is_secure or render_terminates_tls() else 'no-referrer-when-downgrade')
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
    if request.is_secure or render_terminates_tls():
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.get('/sportspace')
@app.get('/ring')
def sportspace():
    return redirect('/static/sportspace/index.html')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "application": "8Byte DevOps Assignment",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "database_health": "/health/db",
            "users": "/users"
        }
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """
    ALB health check endpoint.

    Intentionally does not depend on PostgreSQL so the ALB
    can determine whether the application process itself
    is healthy.
    """
    return jsonify({
        "status": "healthy"
    }), 200


@app.route("/health/db", methods=["GET"])
def database_health():
    try:
        test_database_connection()

        return jsonify({
            "status": "healthy",
            "database": "connected"
        }), 200

    except Exception:
        logger.exception("Database health check failed")

        return jsonify({
            "status": "unhealthy",
            "database": "disconnected"
        }), 503


@app.route("/users", methods=["POST"])
def add_user():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "error": "JSON request body required"
        }), 400

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()

    if not name or not email:
        return jsonify({
            "error": "name and email are required"
        }), 400

    try:
        user = create_user(name, email)

        logger.info("User created successfully")

        return jsonify({
            "message": "User created successfully",
            "user": user
        }), 201

    except ValueError as error:

        return jsonify({
            "error": str(error)
        }), 409

    except Exception:

        logger.exception("Failed to create user")

        return jsonify({
            "error": "Internal server error"
        }), 500


@app.route("/users", methods=["GET"])
def list_users():

    try:

        users = get_users()

        return jsonify({
            "count": len(users),
            "users": users
        }), 200

    except Exception:

        logger.exception("Failed to retrieve users")

        return jsonify({
            "error": "Internal server error"
        }), 500


if __name__ == "__main__":

    try:
        initialize_database()
        logger.info("Database initialized successfully")

    except Exception:
        logger.exception("Database initialization failed")

    app.run(
        host="0.0.0.0",
        port=8080
    )
