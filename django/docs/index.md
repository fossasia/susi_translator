# SUSI Translator Documentation

Welcome to the SUSI Translator documentation. This project provides a robust, real-time audio transcription and translation system.

## Key Features

- **Real-time Processing**: Stream audio data and receive text/translation with minimal delay.
- **Whisper Integration**: Uses OpenAI's Whisper model (or `whisper.cpp`) for state-of-the-art accuracy.
- **Multi-Tenancy**: Support for multiple isolated streams partitioned by `tenant_id`.
- **Automatic Translation**: Integrated with SUSI AI translation services to convert speech to multiple languages on-the-fly.
- **Swagger API**: Interactive API documentation for easy integration.

## Architecture Overview

The system consists of two main parts:
1. **The Server (Django)**: Receives audio chunks, manages queues, and performs transcription and translation in background threads.
2. **The Clients**:
    - **Audio Grabber**: A browser-based or CLI tool that sends microphone audio to the server.
    - **Listener**: A real-time display interface for viewed transcripts.

## Getting Started

To get started with development or deployment, please refer to the [HACKING.md](../HACKING.md) guide in the repository root for environment setup.
