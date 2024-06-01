# Real-time Audio Transcription

## Purpose
This project aims to provide a real-time audio transcription system, where audio input from a microphone is sent to a server, transcribed, and then displayed to the user in real-time. The project uses a server to do the heavy calculations to do the actual transcription while a lightweight
client just does the audio recording and another client just does the result display.

## Python Files

### transcribe_server.py

This file contains the server-side logic, which:

- Listens for incoming audio chunks from the client
- Transcribes the audio chunks using a speech-to-text engine (e.g. Google Cloud Speech-to-Text)
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
