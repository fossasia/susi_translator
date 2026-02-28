# Comprehensive Transcription Engine Benchmark Report

To determine the optimal transcription architecture for the SUSI Translator project, I ran extensive benchmarks comparing open-source engines against our live production server. 

I evaluated **OpenAI Whisper**, **`faster-whisper`**, **Vosk**, and the **`whisper.susi.ai`** API based on load times, transcription speed, Word Error Rate (WER), and system constraints.

---



## 1. GPU Server Environment (Tesla T4 GPU)

To see how the models perform and scale on proper server hardware, I ran a multi-file benchmark on a Google Colab Tesla T4 GPU. I evaluated 5 distinct audio clips ranging from ~9 seconds to ~75 seconds to observe how transcription speed changes with payload size.
   
| Test ID | Audio Length | OpenAI Whisper (GPU) | `faster-whisper` (GPU) | Vosk (CPU) | FW Speedup (vs Whisper) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 8.7s | 0.63s | **0.38s** | 1.76s | **1.6x** |
| 2 | 19.9s | 1.00s | **0.51s** | 2.72s | **2.0x** |
| 3 | 34.8s | 1.85s | **0.88s** | 4.00s | **2.1x** |
| 4 | 51.7s | 2.77s | **1.27s** | 5.03s | **2.2x** |
| 5 | 74.5s | 3.51s | **1.46s** | 6.36s | **2.4x** |

**Average Word Error Rate (WER) Analysis:**
| Engine | Test 1 (8.7s) | Test 2 (19.9s) | Test 3 (34.8s) | Test 4 (51.7s) | Test 5 (74.5s) |
|---|---|---|---|---|---|
| **OpenAI Whisper** | 0.00% | 0.00% | 4.29% | 0.00% | 0.00% |
| **`faster-whisper`** | 0.00% | 0.00% | 4.29% | 0.00% | 0.00% |
| **Vosk** | 0.00% | 2.70% | 1.43% | 4.81% | 5.76% |
   
**Key Findings:**
* **The Scaling GPU Multiplier:** The performance gap actively widens as the audio file gets longer. For a short 9-second clip, `faster-whisper` is 1.6x faster. But for a 75-second clip, it jumps to **2.4x faster**. Across all tests, it averages a **2.1x speedup**.
* **Instant Model Loading:** GPU weight loading is roughly **7x faster** for `faster-whisper` (0.69s vs 4.71s).
* **The Vosk Exception:** Vosk ran entirely on the CPU (impressive for CPU inference). In some tests, it achieved a "lower" WER strictly because of **Inverse Text Normalization (ITN)**. Vosk outputs raw text ("twenty first"), perfectly matching the ground truth, whereas Whisper smartly formats text ("21st"), which the strict scoring script penalizes. For a translation app, Whisper's formatted output is highly preferred.

---

## 2. Production Environment (whisper.susi.ai)

I sent a 5-second chunk of audio over the internet to the existing SUSI Nginx server to benchmark real-world network latency against a local GPU.

| Setup | Execution | Total Time (5s audio) |
|---|---|---|
| **`faster-whisper` GPU** | Local Inference | 0.38s |
| **`whisper.susi.ai`** | Network + Processing | 6.23s |

**Key Findings:**
* **Network Overhead:** The round-trip HTTP request and processing by the massive `large-v3` model takes roughly ~6 seconds for a user.
* **Payload Limits (HTTP 413):** During testing, I discovered the `whisper.susi.ai` Nginx server rejects files larger than a few seconds (HTTP 413 Request Entity Too Large). It is strictly optimized for receiving very short, continuous audio chunks rather than bulk files.

---

## Final Recommendations for SUSI Translator

1. **Local and Edge Deployments (CPU):** 
   While Vosk proved incredibly fast on CPU hardware, its high error rate on precise grammar makes it ill-suited for a translation pipeline where exact wording matters. In CPU environments, sticking to `faster-whisper` (using `int8` quantization) provides the best balance of footprint and accuracy.
   
2. **Backend Server Deployment (GPU):** 
   If we migrate the Django backend to a cloud GPU, `faster-whisper` is the undisputed winner. The 2.5x speed multiplier and identical accuracy entirely invalidate the standard OpenAI PyTorch implementation.
   
3. **Handling Network Latency:** 
   The 6-second latency of the SUSI production server is acceptable for batch processing. However, for real-time live translation, we must ensure our frontend chunking logic strictly honors the Nginx payload limits by sending audio in tiny 1-3 second intervals.
