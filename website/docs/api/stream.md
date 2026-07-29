---
sidebar_position: 3
---

# Translation Stream

The SUSI Translator supports two streaming protocols for receiving real-time transcripts and translations. Both routes are tightly integrated with the core Gevent architecture.

## 1. Server-Sent Events (SSE)

**Endpoint**: `GET /api/v1/translate/stream`

This is the standard, unidirectional Server-Sent Events endpoint.

- **Nginx Tuning**: This route completely bypasses Nginx buffering via `proxy_buffering off;`.
- **Use Case**: Best used when the client only needs to _listen_ to a stream (e.g., an audience member on a mobile device where WebSockets might be blocked by aggressive cellular firewalls).

### Connection Parameters (Query)

| Parameter       | Required | Description                                                                    |
| --------------- | -------- | ------------------------------------------------------------------------------ |
| `tenant_id`     | Yes      | The room UUID to join.                                                         |
| `target_lang`   | No       | Target translation language (e.g., `es`). If `original`, it skips translation. |
| `last_chunk_id` | No       | Integer for resumption. Defaults to 0.                                         |
| `audio`         | No       | If true, the server will trigger TTS generation and send `audio_b64` payloads. |

---

## 2. WebSockets (Bidirectional)

**Endpoint**: `WS /ws/v1/translate/stream`

This endpoint is managed by `flask_sock` and is vastly superior for the **Organizer** as it allows the client to stream raw microphone audio _up_ to the server on the same socket that receives translations _down_.

### The Handler Loop (`_translate_stream_ws_handler`)

Understanding the internal Gevent loop is crucial for contributors:

1. **The Throttling Mechanism**: We implement a time-based throttle (`throttle_interval`) so we don't spam translation APIs (like Google/DeepL) with every 100ms partial audio frame.
2. **The `last_chunk_id` Cursor**: The system maintains a sorted numerical cursor. If a connection drops, the client passes `last_chunk_id=42` on reconnect. The server skips iterating over the first 41 chunks, immediately catching the client up without redelivering duplicate text.
3. **Idle Timeouts (`ws.receive(timeout=0.2)`)**: In our architecture, we cannot use `time.sleep()` inside the loop, because it would block the socket from processing incoming TCP Ping/Pong and Close frames. Using `ws.receive(timeout=0.2)` safely yields execution back to Gevent while allowing us to instantly detect `ConnectionClosed` events.
4. **Connection Caps**: To prevent FD (File Descriptor) exhaustion attacks, connections are tracked via `stream_connections` lock and capped by `MAX_STREAM_CONNECTIONS_PER_TENANT`.

---

## Payload Formats

Both SSE and WebSockets emit identical JSON payload structures. (WebSockets use `json.dumps(payload)` directly).

### Transcript & Translation Payload

```json
{
  "chunk_id": "42",
  "transcript": "Hello world.",
  "translation": "Hola mundo."
}
```

### TTS Payload (If `audio=true`)

When a translated sentence boundary is reached, the async TTS worker (`SizeBoundedTTSCache`) intercepts it and attaches audio:

```json
{
  "chunk_id": "42",
  "transcript": "Hello world.",
  "translation": "Hola mundo.",
  "audio_b64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AA..."
}
```
