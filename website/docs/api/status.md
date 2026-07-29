---
sidebar_position: 5
---

# Translation Status

**Endpoint**: `GET /api/v1/translate/status/<tenant_id>`

Retrieves the current status of the translation process for a specific tenant.

## The Need for Polling

While WebSockets handle real-time delivery beautifully, file-based translation (e.g. uploading a 2-hour MP3) runs asynchronously. A WebSocket might not be open while the file processes.

This endpoint provides a RESTful way for the frontend to poll for task completion.

---

## Request

- **Method**: `GET`
- **Path Parameters**:
  - `tenant_id` (Required): The ID of the tenant whose task you are querying.
- **Authentication**: Not strictly required for checking generic status, but deeply detailed responses may be guarded.

## Response

### Success (200 OK)

```json
{
  "status": "warming_up"
}
```

_If models have fully loaded into memory:_

```json
{
  "status": "ready"
}
```

_If a model failed to load (e.g. out of memory):_

```json
{
  "status": "failed",
  "message": "Translation Error: CUDA out of memory."
}
```

### Architectural Note on State

Currently, status metrics for file processing might be tracked in memory or via database fields on the `Room` object. For extreme multi-node scalability in the future, these status checks would read from a shared Redis cache or a Celery task backend.
