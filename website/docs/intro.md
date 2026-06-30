---
sidebar_position: 1
---

# Introduction

Welcome to the **SUSI Translator** documentation!

## Overview

SUSI Translator is an open-source, powerful backend service designed to handle **real-time multimodal translation** and **transcription** with strict tenant isolation. It bridges the gap between spoken audio and translated text, providing a highly scalable architecture for events, conferences, and individual use cases.

## The Problem Space

Modern translation services often struggle with two distinct use cases simultaneously:

1. **Real-time Streaming**: Delivering captions with ultra-low latency during a live event.
2. **Batch Processing**: Translating large pre-recorded audio files efficiently.

**SUSI Translator** solves this by offering a unified Flask-based API that abstracts away the complexity of managing different transcription engines (like Whisper) and translation APIs, providing both RESTful endpoints for batch jobs and WebSocket/SSE endpoints for real-time streaming.

## Core Features

- **Bi-directional WebSockets**: Built on `simple-websocket` for lowest possible latency during live speech-to-text.
- **Pluggable Provider Registry**: Easily swap out transcription models (e.g., local Whisper vs. cloud APIs) without altering client code.
- **Tenant Isolation**: Every stream and configuration is scoped to a unique `tenant_id` (or Room), protected by JWT authentication.
- **Robust File Handling**: Secure file upload pipelines preventing path traversal and enforcing payload limits.

---

### Navigation Guide

- **[Architecture & Concepts](/docs/category/concepts)**: Dive deep into our design choices, threading models, and why we built the system the way we did.
- **[API Reference](/docs/category/api-reference)**: Explore the detailed REST and WebSocket endpoints.
