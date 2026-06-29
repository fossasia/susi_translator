---
sidebar_position: 1
---

# Upload File

**Endpoint**: `POST /api/v1/translate/upload_file`

This endpoint handles the batch uploading of audio files for asynchronous processing.

## Why Batch Processing?

While the system is optimized for real-time WebSockets, many use-cases involve post-event translation (e.g., uploading a recorded lecture). This endpoint safely ingests those files.

---

## Request

- **Method**: `POST`
- **Content-Type**: `multipart/form-data`
- **Authentication**: JWT Bearer Token (`@organizer_required`)

### Payload

| Field        | Type | Description                    |
| ------------ | ---- | ------------------------------ |
| `audio_file` | File | The audio file to be uploaded. |

:::info Allowed Extensions
To prevent malicious file execution, the system strictly enforces file extensions: `'mp3', 'wav', 'm4a', 'ogg', 'flac', 'mp4', 'aac'`.
:::

## Security & Implementation Details

### 1. Payload Limits

The server enforces a strict `10 * 1024 * 1024` (10MB) limit.

- **Why?**: Audio files can be massive. Unbounded uploads can lead to Memory Exhaustion (OOM) or Disk filling attacks.
- **Implementation**: We check both the `Content-Length` header _and_ perform a safe read chunking (`file.read(MAX_UPLOAD_SIZE + 1)`) to catch spoofed headers.

### 2. Secure Filenames

Uploaded files are never saved with their raw user-provided names.

- **Why?**: A file named `../../../etc/passwd` could lead to Path Traversal vulnerabilities.
- **Implementation**: We use Werkzeug's `secure_filename` combined with a `uuid.uuid4().hex` prefix to guarantee uniqueness and prevent directory traversal.

---

## Response

### Success (200 OK)

```json
{
  "status": "success",
  "file_path": "/secure/path/to/uuid_filename.mp3"
}
```

### Errors

- **413 Payload Too Large**: If the file exceeds 10MB.
- **415 Unsupported Media Type**: If the extension is not in the allowed list.
- **400 Bad Request**: If the file is missing from the form data.
