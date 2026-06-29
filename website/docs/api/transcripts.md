---
sidebar_position: 7
---

# Transcript Management

The Transcript API provides RESTful access to the historical transcript data generated during a streaming session.

:::info Note
During an active WebSocket session, clients receive transcripts in real-time. These endpoints are typically used by secondary clients, or by the primary client when reconnecting to fetch missed history.
:::

---

## Endpoints

### 1. `GET /transcripts`

Retrieves all historical transcripts for a specific session.

**Query Parameters**:

- `tenant_id` (Required): The room or session ID.

**Response (200 OK)**:

```json
{
  "status": "success",
  "transcripts": [
    {
      "chunk_id": "1",
      "text": "Hello world"
    }
  ]
}
```

### 2. `GET /transcripts/latest`

Retrieves the most recent transcript chunk.

**Query Parameters**:

- `tenant_id` (Required): The room or session ID.

**Response (200 OK)**:

```json
{
  "status": "success",
  "chunk_id": "42",
  "text": "Welcome to the keynote."
}
```

### 3. `GET /transcripts/<chunk_id>`

Retrieves a specific transcript chunk by its ID. Useful for verifying missed packets.
