import os
import logging
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_log = logging.getLogger(__name__)

bcrypt = Bcrypt()

_storage_uri = os.environ.get("REDIS_URL", "memory://")
if _storage_uri == "memory://":
    _log.warning(
        "REDIS_URL is not set, rate-limiter is using in-process memory storage. "
        "Limits will not be shared across Gunicorn workers and will reset on restart. "
        "Set REDIS_URL in .env for correct multi-worker behaviour."
    )

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
)
