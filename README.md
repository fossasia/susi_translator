# Real-time Audio Transcription

## Purpose
This project aims to provide a real-time audio transcription system, where audio input from a microphone is sent to a server, transcribed, and then displayed to the user in real-time. The project uses a server to do the heavy calculations to do the actual transcription while a lightweight
client just does the audio recording and another client just does the result display.

## Python Files

### transcribe_server.py

This file contains the server-side logic, which:

- Listens for incoming audio chunks from the client
- Transcribes the audio chunks using whisper
- Returns the transcribed text to the client

### audio_grabber.py

This file contains the client-side logic, which:

- Captures audio from the microphone
- Chunks the audio into manageable pieces
- Sends the audio chunks to the server with a unique chunk ID

## HTML Files

### transcribe_listener.html

This file contains the client-side logic, which:

- Listens to the server for transcribed chunks
- Displays the transcribed text to the user in real-time

## Setup and Run

To set up and run the project, follow these steps:

* Install the required Python packages: pyaudio, flask, requests, whisper
* Run `audio_grabber.py` to start capturing audio from the microphone
* Run `transcribe_server.py` to start the server
* Open `transcribe_listener.py` in the browser to start displaying transcribed text in real-time

## GSoC 2026 Proposal: Real-Time AI Live-Interpretation

### Overview
This proposal aims to transition the **SUSI Translator** into a high-performance, real-time interpretation engine for the `eventyay-video` ecosystem. By moving from batch processing to a **Streaming Inference Pipeline**, we can achieve sub-second latency for live event subtitles.

### Proposed 3-Tier Architecture
To minimize latency and handle high-throughput event data, I am implementing a modular system:

1.  **Audio Ingestion (Client):** A lightweight Flutter/Web-based "Audio Grabber" that chunks live microphone input into 500ms - 2000ms segments.
2.  **Inference Server (Core):** A Python-based backend utilizing `faster-whisper` and `ggml-large-v3` models. This server handles VAD (Voice Activity Detection) and asynchronous transcription.
3.  **Real-Time Listener (UI):** A WebSocket-driven interface that overlays translated subtitles directly onto the live video player.

### Setup Prototyping (Preview)
Initial logic for the real-time transcription workflow:
* **Server:** `transcribe_server.py` using Whisper for rapid chunk-to-text conversion.
* **Client:** `audio_grabber.py` for capturing and routing unique chunk IDs to the inference engine.
* **Frontend:** `transcribe_listener.html` for low-latency subtitle display via WebSockets.

### Roadmap
* **Phase 1:** Optimize the Whisper backend for `task='translate'` to support multilingual live interpretation.
* **Phase 2:** Integrate `eventyay-video` components with the WebSocket stream for seamless UI overlays.
* **Phase 3:** Implement load-balancing for high-concurrency event environments.

---
**Contributor:** Aryan Subudhi (GSoC 2026 Applicant)
```
./server -m models/ggml-large-v3.bin -l de -p 16 -t 32 --host 0.0.0.0 --port 8007
```
