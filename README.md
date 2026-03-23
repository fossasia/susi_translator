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

### 1. Install Python dependencies

Open a terminal in the project root and run:

```
pip install -r requirements.txt
```

### 2. Start the transcription server

You can use the one-click script (Windows):

```
start_server.bat
```

Or run manually:

```
python susi_translator/flask/transcribe_server.py
```

### 3. Start the audio grabber client

In a new terminal:

```
python susi_translator/flask/audio_grabber.py
```
You will be prompted to select your microphone device.

### 4. View the transcript in your browser

Open the file `susi_translator/flask/transcribe_listener.html` in your web browser. Enter the server host/port if different from default, and click Connect.

### Features & Improvements

- Robust error handling and user feedback
- Health check endpoint at `/health` for server status
- Device selection for audio input
- Status and error indicators in the HTML client
- Copy transcript button in the HTML client

---
For advanced usage or troubleshooting, see comments in each file.
