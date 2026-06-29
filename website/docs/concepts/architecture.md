---
sidebar_position: 1
---

# Architecture & Concepts

This document explores the internal design decisions, concurrency models, and structural philosophy of the SUSI Translator backend.

As an open-source project, we believe in radical transparency regarding _why_ we built things a certain way, allowing both new and senior contributors to understand the system deeply.

## 1. The Core Stack: Flask with simple-websocket

While many modern Python async frameworks exist (like FastAPI or Sanic), SUSI Translator is built on **Flask**.

### Why Flask?

Flask provides an incredibly mature ecosystem for authentication (`flask-jwt-extended`), database ORM (`SQLAlchemy`), and routing. However, Flask is historically synchronous.

### Why `simple-websocket`?

To achieve real-time bi-directional streaming in a synchronous Flask environment, we opted for `simple-websocket` rather than massive async wrappers or `Flask-SocketIO`.

- **Lower Overhead**: `simple-websocket` runs directly on the Werkzeug development server or production WSGI servers that support WebSocket upgrades.
- **Raw Control**: It gives us raw access to WebSocket frames (text and binary), which is crucial for handling raw audio chunks without the overhead of SocketIO's custom polling protocols.

## 2. Concurrency & Threading

Handling live audio streams requires strict thread safety, especially when multiple WebSocket clients connect to the same translation room.

### The `transcripts_lock` Pattern

Instead of persisting real-time transient captions to a database (which would introduce I/O bottleneck latency), transient state is kept in-memory:

- We use a global `threading.Lock` (`transcripts_lock`) to protect read/write access to the in-memory transcript dictionaries.
- **Why?**: Database round-trips for every 100ms audio chunk would saturate the DB. In-memory locks allow nanosecond-level access.

:::warning Scalability Note
Because state is in-memory, the current architecture expects a single-node deployment for the streaming engine, or sticky sessions if deployed behind a load balancer. Future contributors can look into Redis Pub/Sub for multi-node scaling.
:::

## 3. Tenant & Room Isolation

Every action in the system is scoped to a `tenant_id`.

- **Rooms**: A room is essentially a session owned by an `Organizer`.
- **JWT Authentication**: All sensitive routes use `@organizer_required` and `verify_jwt_in_request`.

### Why Tenant IDs instead of User IDs?

A "Tenant" (or Room) represents the _event_ rather than the _speaker_. Multiple listeners can subscribe to the same `tenant_id` stream. This fan-out architecture ensures we only transcribe the audio once, and broadcast the result to N listeners, saving massive compute costs.

## 4. The Provider Registry

Translation and transcription APIs change rapidly. We use a **Provider Registry Pattern**.

- **Abstraction**: The core WebSocket loop doesn't know if Whisper, Google API, or DeepL is doing the translation. It simply calls `registry.translate()`.
- **Why?**: This allows the frontend to send a `/configure` request to swap the engine dynamically on the fly without restarting the WebSocket connection.
