from functools import wraps
from flask import redirect, url_for, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
import logging

logger = logging.getLogger(__name__)

_INTERNAL_ALLOWED: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/transcripts"),
})


def organizer_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()

            claims = get_jwt()
            if claims.get("role") == "internal":
                allowed = (request.method, request.path) in _INTERNAL_ALLOWED
                if not allowed:
                    logger.warning(
                        f"Internal token rejected for {request.method} {request.path}"
                    )
                    return jsonify({"status": "error", "message": "Forbidden."}), 403

        except (JWTExtendedException, PyJWTError, Exception) as e:
            logger.warning(f"Auth failed for {request.path}: {type(e).__name__}: {e}")
            is_api = request.path.startswith("/api/") or request.is_json
            if is_api:
                return jsonify({"status": "error", "message": "Authentication required."}), 401
            return redirect(url_for("auth.login_page"))

        return fn(*args, **kwargs)

    return wrapper