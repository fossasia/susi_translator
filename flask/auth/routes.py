from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify, render_template
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt,
    get_jwt_identity,
    set_access_cookies,
    unset_jwt_cookies,
)
from sqlalchemy.exc import SQLAlchemyError
from .models import db, Organizer
from .extensions import limiter

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
bcrypt = Bcrypt()


# Page routes
@auth_bp.route("/login")
def login_page():
    return render_template("auth/login.html")


@auth_bp.route("/signup")
def signup_page():
    return render_template("auth/signup.html")

# API routes
@auth_bp.route("/api/signup", methods=["POST"])
@limiter.limit("5 per minute")
def signup():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip()

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters long."}), 400

    if Organizer.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "Email already registered."}), 409

    try:
        pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        organizer = Organizer(email=email, password_hash=pw_hash, name=name)
        db.session.add(organizer)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error during signup: {str(e)}")
        return jsonify({"status": "error", "message": "An internal server error occurred. Please try again."}), 500

    token = create_access_token(identity=organizer.email)

    response = jsonify({
        "status": "success",
        "message": "Account created successfully.",
        "email": organizer.email,
        "name": organizer.name or "",
    })
    set_access_cookies(response, token)
    return response, 201


@auth_bp.route("/api/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    organizer = Organizer.query.filter_by(email=email).first()
    if not organizer or not bcrypt.check_password_hash(organizer.password_hash, password):
        return jsonify({"status": "error", "message": "Invalid email or password."}), 401

    token = create_access_token(identity=organizer.email)

    response = jsonify({
        "status": "success",
        "message": "Login successful.",
        "email": organizer.email,
        "name": organizer.name or "",
    })
    set_access_cookies(response, token)
    return response, 200


@auth_bp.route("/api/logout", methods=["POST"])
@jwt_required()
def logout():
    jti = get_jwt()["jti"]
    from .models import TokenBlocklist
    try:
        db.session.add(TokenBlocklist(jti=jti))
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error during logout: {str(e)}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

    response = jsonify({"status": "success", "message": "Logged out successfully."})
    unset_jwt_cookies(response)
    return response, 200


@auth_bp.route("/api/me", methods=["GET"])
@jwt_required()
def me():
    """Return the current authenticated organizer's profile."""
    email = get_jwt_identity()
    organizer = Organizer.query.filter_by(email=email).first()
    if not organizer:
        return jsonify({"status": "error", "message": "User not found."}), 404
    return jsonify({
        "status": "success",
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "name": organizer.name or "",
        },
    }), 200


@auth_bp.route("/api/status", methods=["GET"])
@jwt_required(optional=True)
def status():
    
    email = get_jwt_identity()
    if email:
        organizer = Organizer.query.filter_by(email=email).first()
        if organizer:
            return jsonify({
                "authenticated": True,
                "email": organizer.email,
                "name": organizer.name or "",
            }), 200
    return jsonify({"authenticated": False}), 200