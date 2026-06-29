---
sidebar_position: 8
---

# Event Lifecycle

The Event API manages the lifecycle of translation events and rooms.

---

## Endpoints

### 1. `POST /stop_event/<tenant_id>`

Gracefully terminates a translation event.

**Why is this endpoint needed?**
When an event finishes, it's not enough to simply disconnect the WebSockets. Background tasks (like file translation polling or background chunk transcribers) might still be spinning. This endpoint cleans up memory by:

1. Clearing the `transcripts_lock` dictionaries for the given `tenant_id`.
2. Broadcasting a termination frame to all connected WebSocket clients.
3. Updating the Room status in the database to `finished`.

**Authentication**: JWT Bearer Token (`@organizer_required`).

**Response (200 OK)**:

```json
{
  "status": "success",
  "message": "Event stopped and resources cleaned up."
}
```

### 2. `POST /internal/token-refresh`

Refreshes short-lived translation provider tokens (like temporary API keys for external services) during long-running events to ensure the stream does not drop due to external API token expiration.
