---
sidebar_position: 1
---

# SUSI Translator

This guide provides a comprehensive walkthrough for Event Organizers on how to operate the SUSI Translator system via the frontend interface.

## 1. Account Management

Before hosting an event, you must create an Organizer account.

- Navigate to the `/signup` page.
- You must provide a valid email, name, and a password (minimum 8 characters).
- Behind the scenes, the system uses `bcrypt` to hash your password and issues a secure `HTTP-Only` JWT cookie.

Once registered, you can log in at `/login`. This JWT cookie will authenticate you across all API requests seamlessly.

## 2. Configuring an Event (Room)

When you log into the dashboard, your browser connects to your unique "Room" (mapped internally to a `tenant_id`).

### Translation Settings

You can dynamically configure your provider settings:

1. **Transcription Provider**: Select the AI model for Speech-to-Text (e.g., local Whisper vs Cloud Speech API).
2. **Translation Provider**: Select the Text-to-Text translation engine (e.g., DeepL or Google Translate).
3. **Languages**: Set the `Source Language` (the language spoken by the presenter) and `Target Language` (the language your audience wants to read).

> **Note**: These settings can be changed _during_ a live stream. The backend `ProviderRegistry` will dynamically swap the engines for the next incoming audio chunk without dropping active WebSockets.

## 3. Streaming Live Audio

### Web Microphone

To start live captioning:

- Navigate to the `Stream` tab.
- Click **Start Microphone**.
- The browser captures audio in raw binary chunks and streams it up to the server via WebSockets (`ws://.../ws/v1/translate/stream`).

### The Audience View

- Your audience can connect to your unique Room URL (e.g. `/stream/<tenant_id>`).
- As you speak, the translation engine processes the chunks and broadcasts JSON payloads containing `chunk_id`, `transcript`, and `translation`.
- The frontend dynamically updates the UI to append these captions in real-time.

## 4. Batch File Translation

If you have pre-recorded audio (like a podcast or a recorded lecture), you don't need to stream it live:

1. Go to the **Upload** section in your dashboard.
2. Select an audio file. The system accepts `mp3`, `wav`, `m4a`, `ogg`, `flac`, `mp4`, `aac`.
3. The server enforces a **10MB limit** per file.
4. Once uploaded, the file is queued for processing. You can poll the status endpoint to check the progress of the translation, and eventually download the translated captions as a text file.

## 5. Ending an Event

When the event is over, click **Stop Event**.
This is a critical operation. It tells the server to:

1. Stop the WebSocket broadcast loop.
2. Purge the in-memory transcript dictionaries (`transcripts_lock`) to free up server RAM.
3. Disconnect all audience members.
