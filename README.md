# Real-time Audio Transcription

## Purpose
This project aims to provide a real-time audio transcription system, where audio input from a microphone is sent to a server, transcribed, and then displayed to the user in real-time. The project uses a server to do the heavy calculations to do the actual transcription while a lightweight client just does the audio recording and another client just does the result display.

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


## Requirements

### Python Version
- **Recommended: Python 3.11**
- Python 3.14+ is not supported - too new for most required packages

## Setup and Run

### Option A — pip (classic)
```bash
pip install -r requirements.txt
```

### Option B — uv (recommended, faster)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. Install it first:
```bash
# macOS / Linux
curl -Ls https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install dependencies:
```bash
uv sync
```

* Run `audio_grabber.py` to start capturing audio from the microphone
* Run `transcribe_server.py` to start the server
* Open `transcribe_listener.html` in the browser to start displaying transcribed text in real-time