---
sidebar_position: 2
---

# Deployment & Infrastructure

The SUSI Translator is designed to be fully containerized and autonomous in production. We use **Docker Compose** to orchestrate four primary services.

This document explains why the infrastructure is designed this way and how the services interact, particularly regarding automated SSL.

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

## 2. The Automated SSL Loop (Certbot & Nginx)

One of the hardest parts of Dockerized SSL is the dependency loop: **Nginx will crash if it starts without SSL certificates, but Certbot cannot validate your domain until the web server is running.**

We solve this using a self-healing loop:

### Step 1: Dummy Bootstrapping

When the Nginx container starts, an entrypoint script (`bootstrap_ssl.sh`) checks the shared `/etc/letsencrypt` volume.

- If real certificates do not exist, it runs `openssl` to instantly generate self-signed "dummy" certificates.
- Nginx successfully binds to port `443` using these dummy certs.

### Step 2: DuckDNS DNS-01 Challenge

The `certbot` container wakes up and attempts to get a real Let's Encrypt certificate.

- Instead of a traditional HTTP-01 challenge (which requires port 80 to be open to the internet), it uses a **DNS-01 hook** (`authenticator.sh`).
- It pings the DuckDNS API to inject the validation token directly into your domain's TXT records.
- After a 30-second delay for DNS propagation, Let's Encrypt verifies the record and issues the certificates to the shared volume.

### Step 3: The Seamless Reload

Inside the Nginx container, a background script runs an infinite loop: `sleep 6h; nginx -s reload`.

- As soon as Certbot provisions the new real certificates, the Nginx background loop reloads the configuration.
- Nginx instantly swaps the dummy certificates for the real ones in-memory, without dropping a single active WebSocket connection!
