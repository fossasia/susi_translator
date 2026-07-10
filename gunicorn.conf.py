"""
gunicorn.conf.py Production configuration for susi_translator Flask app
"""

import os

# Binding
host = os.getenv("FLASK_HOST", "127.0.0.1")
port = os.getenv("FLASK_PORT", "5040")
bind = f"{host}:{port}"


# Worker config

# keep workers=1, the app uses in-process shared state.
workers = 1
worker_class = "gevent"
worker_connections = 1000  # concurrent greenlet connections per worker


# Timeouts
timeout = 0
graceful_timeout = 30 # seconds to wait for workers to finish on SIGTERM
keepalive = 5 # seconds to keep HTTP keep-alive connections open

# Logging
accesslog = "-" # stdout
errorlog = "-" # stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "susi_translator"

# Reload
reload = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes", "on")
