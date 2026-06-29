---
sidebar_position: 1
---

# Setup and Installation

This document explains how to set up, configure, and run the SUSI Translator Flask backend locally or in production.

## Prerequisites

- **Python 3.10+**
- **uv**: The ultra-fast Python package installer and resolver.
- **SQLite or PostgreSQL**: For the Organizer database.

## 1. Environment Configuration

The application relies heavily on environment variables for API keys and secrets. You must copy the example environment file and fill it out:

```bash
cp flask/.env.example flask/.env
```

### Critical Variables

- `JWT_SECRET_KEY`: A long, random cryptographic string used to sign user cookies. If this leaks, attackers can forge auth tokens. Minimum 32 characters.
- `DATABASE_URL`: Connection string for the database. Defaults to SQLite (`sqlite:///susi.db`) for local development; PostgreSQL is recommended for production.
- `CORS_ALLOWED_ORIGINS`: Comma-separated list of origins allowed to call the API from a browser.

## 2. Database Setup

SUSI uses Flask-Migrate (Alembic) and SQLAlchemy. To initialize your database schema, run the following commands inside the `flask/` directory:

```bash
uv run flask db upgrade
```

This will create a `translations.db` (SQLite) by default, generating the `Organizer`, `Room`, and `TokenBlocklist` tables.

## 3. Running the Server

To start the server, use the `uv` tool to execute the entrypoint script:

```bash
cd flask
uv run python run.py
```

### Why not Gunicorn?

For local development, `run.py` launches the Werkzeug development server. Because we rely on `simple-websocket` for bidirectional streaming, running behind a WSGI server like Gunicorn requires specific worker classes (like Eventlet or Gevent).

If deploying to production, you must use a WebSocket-compatible WSGI server setup. For example:

```bash
gunicorn --worker-class eventlet -w 1 run:app
```

_(Note: Because the backend relies on an in-memory `threading.Lock` for `transcripts_lock`, you must currently restrict it to a single worker `-w 1` or implement Redis Pub/Sub for multi-worker scaling)._
