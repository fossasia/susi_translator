from flask import redirect, url_for, request
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
import logging

from auth.models import Organizer

logger = logging.getLogger(__name__)


class SecureModelView(ModelView):
    """
    A custom ModelView for Flask-Admin that checks for a valid JWT token
    and ensures the authenticated Organizer has the is_admin flag set to True.
    """
    column_exclude_list = ['password_hash']
    form_excluded_columns = ['password_hash']

    def is_accessible(self):
        try:
            verify_jwt_in_request(locations=["cookies"])
            email = get_jwt_identity()
            if email:
                user = Organizer.query.filter_by(email=email).first()
                if user and user.is_admin:
                    return True
        except (JWTExtendedException, PyJWTError):
            # Expected: missing/invalid/expired token
            pass
        # All other exceptions (DB errors, programmer errors) propagate so they
        # appear in logs rather than being silently misreported as auth failures.
        return False

    def inaccessible_callback(self, name, **kwargs):
        try:
            identity = get_jwt_identity()
        except RuntimeError:
            identity = "anonymous"
        logger.warning(f"Unauthorized admin access attempt to {name!r} by {identity!r}")
        return redirect(url_for('auth.login_page', next=request.url))


class SecureAdminIndexView(AdminIndexView):
    """ Protects the /admin/ root dashboard """
    def is_accessible(self):
        try:
            verify_jwt_in_request(locations=["cookies"])
            email = get_jwt_identity()
            if email:
                user = Organizer.query.filter_by(email=email).first()
                if user and user.is_admin:
                    return True
        except (JWTExtendedException, PyJWTError):
            # missing/invalid/expired token gives deny access.
            pass
        # All other exceptions propagate.
        return False

    def inaccessible_callback(self, name, **kwargs):
        try:
            identity = get_jwt_identity()
        except RuntimeError:
            identity = "anonymous"
        logger.warning(f"Unauthorized admin index access attempt to {name!r} by {identity!r}")
        return redirect(url_for('auth.login_page', next=request.url))