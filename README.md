# SUSI Translator: Real-time Audio Transcription & Translation

SUSI Translator is a powerful system for real-time audio transcription and translation. It captures audio from a client (microphone or desktop), processes it using OpenAI's Whisper model on a server, and displays results in real-time.

## Features

- **Real-time Transcription**: Continuous processing of audio streams with low latency.
- **Multi-Tenant Support**: (Django) Partitioned processing for different users/tenants.
- **Language Translation**: (Django) Integrated translation into multiple target languages via SUSI AI services.
- **Flexible Deployment**: Choose between a lightweight Flask server or a full-featured Django backend.
- **Model Options**: Support for local Whisper models or optimized `whisper.cpp` servers.

## Project Structure

- `flask/`: Lightweight implementation, ideal for quick setups and simple use cases.
- `django/`: Advanced implementation with multi-tenancy, translation, and Swagger API docs.
- `models/`: Directory for storing Whisper model weights (`.pt` or `.bin`).

---

## ⚡ Quick Start (Flask)

The Flask version is the simplest way to get started.

1. **Install Dependencies**:
   ```bash
   pip install flask flask-cors requests pyaudio openai-whisper torch numpy
   ```
2. **Start Server**:
   ```bash
   cd flask
   python transcribe_server.py
   ```
3. **Run Audio Grabber**:
   ```bash
   python audio_grabber.py
   ```
4. **View Results**:
   Open `transcribe_listener.html` in your browser.

---

## 🚀 Advanced Setup (Django)

The Django version provides robust API management and translation services.

1. **Setup Environment**:
   Follow the detailed guide in [django/HACKING.md](django/HACKING.md).
2. **Run Server**:
   ```bash
   cd django
   python manage.py runserver 0.0.0.0:5040
   ```
3. **API Documentation**:
   Visit `http://localhost:5040/swagger/` for interactive API docs.

---

## Technical Details

### Workflow
- **Client**: Captures audio, detects silence chunks, and POSTs base64 audio to the server.
- **Server**: Queues incoming chunks, transcribes them using Whisper in a background thread, and optionally translates the text.
- **Output**: Clients poll or listen for finalized transcripts.

## License
Apache License Version 2.0. See `LICENSE` for details.
