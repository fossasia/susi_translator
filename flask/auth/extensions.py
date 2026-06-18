import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_storage_uri = os.environ.get("REDIS_URL", "memory://")
limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri)
