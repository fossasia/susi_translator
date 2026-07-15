---
sidebar_position: 1
---

# Architecture & Concepts

This document explores the internal design decisions, concurrency models, and structural philosophy of the SUSI Translator backend.

As an open-source project, we believe in radical transparency regarding _why_ we built things a certain way, allowing both new and senior contributors to understand the system deeply.

## 1. The Core Stack: Flask with Gunicorn & Gevent

While many modern Python async frameworks exist (like FastAPI or Sanic), SUSI Translator is built on **Flask**.

### Why Flask?

Flask provides an incredibly mature ecosystem for authentication (`flask-jwt-extended`), database ORM (`SQLAlchemy`), and routing. However, Flask is historically synchronous.

### Concurrency with Gevent

To achieve massive concurrency for real-time audio streaming and Server-Sent Events (SSE), we deploy the application using **Gunicorn with Gevent workers**.

- **Greenlets over Threads**: Instead of using OS-level threads which are heavy and block on I/O, Gevent uses lightweight "greenlets". A single Gunicorn worker can handle thousands of concurrent WebSocket and SSE connections asynchronously.
- **Monkey Patching**: Gevent monkey-patches standard library threading and I/O structures. This allows us to use traditional tools like `queue.Queue` (`audio_stack`) safely without introducing deadlocks.

## 2. The Audio Pipeline & Threading

Handling live audio streams requires strict thread safety, especially when multiple clients connect to the same translation room.

### The `audio_stack` Queue

Incoming audio chunks are immediately decoded and pushed to `audio_stack` (a FIFO queue). A background daemon thread (`process_audio()`) continuously consumes this queue.

- **Optimization**: To save CPU cycles, the `_next_payload()` function checks the queue size. If a client uploads multiple versions of the exact same audio chunk (e.g., from network lag), it smartly drops superseded duplicates and only processes the latest chunk.

### In-Memory Locking

Instead of persisting real-time transient captions to a database (which would introduce I/O bottleneck latency), transient state is kept in-memory:

- We use a global `threading.Lock` (`transcripts_lock`) to protect read/write access to the in-memory transcript dictionaries.
- **Why?**: Database round-trips for every 100ms audio chunk would saturate the DB. In-memory locks allow nanosecond-level access.

:::warning Scalability Note
Because state is in-memory, the current architecture expects a single-node deployment for the streaming engine, or sticky sessions if deployed behind a load balancer. Future contributors can look into Redis Pub/Sub for multi-node scaling.
:::

## 3. Subprocess Management (Audio Grabbers)

For URL and YouTube streams, the server launches background `audio_grabber.py` instances using `subprocess.Popen`.

- The PIDs are tracked in a shared `grabber_processes` dictionary.
- When a stream is stopped or the server shuts down, strict `SIGTERM` and `SIGKILL` (via `atexit`) signals are sent to prevent zombie `ffmpeg` processes from leaking memory.

## 4. TTS Optimization (Supertonic)

Text-To-Speech inference is computationally expensive. SUSI Translator includes a highly optimized engine:

- **`SizeBoundedTTSCache`**: An LRU-style dictionary that strictly caps memory usage at 50MB. Old audio payloads are evicted to prevent OOM crashes.
- **Inference Locking**: A dedicated `tts_inference_lock` and a ThreadPoolExecutor (`max_workers=1`) ensure that parallel threads don't attempt simultaneous TTS generation, protecting the CPU/GPU from contention.

## 5. The Provider Registry

Translation and transcription APIs change rapidly. We use a **Provider Registry Pattern**.

- **Abstraction**: The core WebSocket loop doesn't know if Whisper, Google API, or DeepL is doing the translation. It simply calls `registry.transcribe()`.
- **Why?**: This allows the frontend to send a `/configure` request to swap the engine dynamically on the fly without restarting the connection.
