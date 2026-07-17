---
sidebar_position: 2
---

# Deployment & Infrastructure

The SUSI Translator is designed to be fully containerized and autonomous in production. We use **Docker Compose** to orchestrate four primary services.

This document explains why the infrastructure is designed this way and how the services interact.

## 1. The Core Services

### A. Database (`db`)

- **Image**: `postgres:15.7`
- **Purpose**: Persists user accounts, tokens, and room session metadata.
- **Why Postgres?**: While the app supports SQLite for local dev, Gunicorn's Gevent workers process hundreds of concurrent queries. SQLite uses file-level locking which throws `database is locked` errors under heavy load. Postgres guarantees row-level concurrency.

### B. Web Backend (`web`)

- **Build Context**: `flask/Dockerfile`
- **Purpose**: Runs the Flask application using Gunicorn and Gevent.
- **Key Details**:
  - Uses `uv` (from Astral) for incredibly fast dependency resolution.
  - An `entrypoint.sh` script guarantees that `flask db upgrade` (Alembic migrations) is run _before_ Gunicorn starts.
  - Memory is strictly capped (e.g., 6G) via the compose `deploy` block to prevent memory leaks from crashing the host machine.

### C. Reverse Proxy (`nginx`)

- **Build Context**: `deployment/nginx/Dockerfile.nginx`
- **Purpose**: Handles SSL termination, HTTP-to-HTTPS redirects, and static file serving.
- **SSE Optimization**: The proxy is specifically tuned to not buffer Server-Sent Events (`proxy_buffering off;`). Without this, Nginx would queue up chunks and introduce massive latency.
