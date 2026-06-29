---
sidebar_position: 4
---

# List Rooms

**Endpoint**: `GET /api/v1/translate/rooms`

Retrieves a list of available translation rooms owned by the currently authenticated Organizer.

## Concept: Rooms vs Tenants

In SUSI Translator, the concepts of "Rooms" and "Tenants" are closely linked.

- A **Tenant ID** represents a single isolated execution environment for a transcription stream.
- A **Room** is the database representation (persisted via SQLAlchemy) of an event, which maps 1:1 to a `tenant_id`.

When an Organizer logs in via JWT, they can list all the Rooms they have created. This allows the frontend dashboard to display all active/historical streams they manage.

---

## Request

- **Method**: `GET`
- **Authentication**: JWT Bearer Token (`@organizer_required`)

## Response

Returns an array of active rooms and their metadata.

### Success (200 OK)

```json
{
  "status": "success",
  "rooms": [
    {
      "tenant_id": "uuid-string",
      "name": "Main Stage Keynote",
      "stream_type": "youtube",
      "created_at": "2026-06-28T10:00:00Z"
    }
  ]
}
```

### Errors

- **401 Unauthorized**: Missing or expired JWT token.
