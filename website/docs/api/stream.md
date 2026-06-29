---
sidebar_position: 3
---

# Translation Stream (WebSockets)

**Endpoint**: `WS /ws/v1/translate/stream`

This is the most complex and critical endpoint in the SUSI Translator architecture. It handles real-time bidirectional communication.

:::note Server-Sent Events (SSE)
We also expose a fallback `GET /api/v1/translate/stream` endpoint using Server-Sent Events. However, the WebSocket implementation is vastly superior for production as it allows the client to stream raw microphone audio _up_ to the server on the same socket that receives translations _down_.
:::

---

## Connection & Request

- **Protocol**: `ws://` or `wss://`
- **Authentication**: JWT tokens passed via cookies or headers.

### Query Parameters

| Parameter       | Required | Description                                                                    |
| --------------- | -------- | ------------------------------------------------------------------------------ |
| `tenant_id`     | Yes      | The room to join.                                                              |
| `source`        | No       | Default is `mic`.                                                              |
| `target_lang`   | No       | Target translation language (e.g., `es`). If `original`, it skips translation. |
| `last_chunk_id` | No       | Integer for resumption. Defaults to 0.                                         |

---

## The Handler Loop (`_translate_stream_ws_handler`)

Understanding the `while ws.connected:` loop is crucial for contributors.

### 1. The Throttling Mechanism

```python
can_translate = (now - last_translation_time) >= throttle_interval
```

- **Why?**: Translation APIs (like Google or DeepL) charge per character and enforce strict rate limits. If we sent every single audio frame's partial transcription to the translator, we would get rate-limited instantly.
- **How**: We implement a time-based throttle (`throttle_interval`) and only allow _one_ translation per loop iteration (`can_translate = False`).

### 2. The `last_chunk_id` Cursor

The system maintains a sorted numerical cursor (`cid_int`).

- **Why?**: If a WebSocket drops on a poor mobile connection, the client can reconnect and pass `last_chunk_id=42`. The server skips iterating over the first 41 chunks, immediately catching the client up. This ensures idempotent, gapless delivery.

### 3. Idle Timeouts and Ping Frames

```python
_ = ws.receive(timeout=0.2)
```

- **Why?**: In synchronous Python WebSockets, control must be yielded to the underlying socket library to process incoming TCP Ping/Pong and Close frames. If we used `time.sleep()`, the socket would silently buffer and eventually crash. By using `ws.receive(timeout)`, we simultaneously sleep the loop and process network events safely.

---

## Payload Formats

### Initial Connection

```json
{
  "status": "connected"
}
```

### Translation Events

Broadcast continuously as audio is processed:

```json
{
  "chunk_id": "1",
  "transcript": "Hello world",
  "translation": "Hola mundo"
}
```
