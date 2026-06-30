---
sidebar_position: 2
---

# Configure Translation

**Endpoint**: `POST /api/v1/translate/configure`

This endpoint dynamically configures the transcription and translation providers for a specific tenant.

## Why Dynamic Configuration?

In live environments, an organizer might realize the default translation engine isn't capturing technical jargon well. This endpoint allows the frontend to swap the underlying AI model (e.g., switching from a fast local model to a highly accurate cloud model) without dropping the active WebSocket connections.

---

## Request

- **Method**: `POST`
- **Content-Type**: `application/json`
- **Authentication**: JWT Bearer Token (`@organizer_required`)

### Payload Schema

```json
{
  "tenant_id": "string (UUID)",
  "transcription": "whisper | google | azure",
  "translation": "deepl | google",
  "source_lang": "en",
  "target_lang": "es",
  "stream_url": "optional string",
  "stream_type": "youtube | file"
}
```

### Parameter Details

- **`tenant_id`** (Required): The room or event ID to configure.
- **`transcription` / `translation`**: Defines which provider from the `ProviderRegistry` to mount. At least one must be provided.
- **`source_lang` / `target_lang`**: ISO language codes.

---

## Internal Architecture Choices

### Ownership Verification

Before applying any configuration, the system calls `_assert_tenant_ownership(tenant_id)`.

- **Why?**: To prevent IDOR (Insecure Direct Object Reference) vulnerabilities. A user must not be able to change the configuration of a room they do not own.

### Stream Type Handling

If a `stream_url` is provided, the system validates it against the `stream_type`.

- If `youtube`, it delegates to `_configure_youtube_stream()`.
- If `file`, it verifies the file exists locally and is within the safe `UPLOAD_FOLDER`.

---

## Response

### Success (200 OK)

```json
{
  "status": "success",
  "message": "Configuration updated successfully."
}
```

### Errors

- **400 Bad Request**: Missing `tenant_id` or both provider fields.
- **403 Forbidden**: Caller does not own the `tenant_id`.
