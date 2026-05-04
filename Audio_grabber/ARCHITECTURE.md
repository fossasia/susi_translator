# Architecture Rationale: Audio Ingestion POC

This document explains the technical decisions made during the implementation of the Audio Ingestion service. It is designed to help contributors understand the core design principles and component choices of the ingestion pipeline.

## 1. URL Resolution (`url_resolver.py`)

The `url_resolver.py` module acts as the initial stage of our audio pipeline. Its core purpose is to convert generic, user-facing streaming links (such as YouTube Live or Twitch URLs) into direct, playable media URLs that our backend can ingest.

- **Tool Selection:** We rely on [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) as our extraction engine. It was selected over lighter libraries because of its highly active open-source community, rapid patching of broken extractors, and built-in support for thousands of streaming sites. This ensures our application remains resilient as third-party platforms update their systems.
- **Extraction Logic:** Our extraction strategy heavily prioritizes HLS (`m3u8`) manifests. HLS (HTTP Live Streaming) is optimal for our use case because it natively handles stream segmentation. By passing an HLS URL down the pipeline, we allow our downstream processor (FFmpeg) to efficiently manage network buffering and chunk retrieval.
- **Environment Safety & Portability:** To guarantee cross-platform compatibility for all contributors, the resolver executes `yt-dlp` securely as a Python module (`python -m yt_dlp`) instead of assuming a system-wide binary installation. This prevents environment-specific bugs and simplifies the developer setup process.
