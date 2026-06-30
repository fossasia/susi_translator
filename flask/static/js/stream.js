document.addEventListener('DOMContentLoaded', () => {

    //Embed the YouTube Video
    const ytPlayer = document.getElementById('yt-player');

    const extractYtId = (url) => {
        const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^&?]+)/);
        return match ? match[1] : null;
    };

    const extractTwitchId = (url) => {
        const match = url.match(/(?:twitch\.tv\/)([^&?\/]+)/);
        return match ? match[1] : null;
    };

    const extractVimeoId = (url) => {
        const match = url.match(/(?:vimeo\.com\/)(?:channels\/(?:\w+\/)?|groups\/(?:[^\/]+\/)?videos\/|video\/|)(\d+)(?:|\/\?)/);
        return match ? match[1] : null;
    };

    if (STREAM_TYPE === 'mic') {
        ytPlayer.style.display = 'none';
        const micContainer = document.getElementById('mic-container');
        if (micContainer) micContainer.style.display = 'flex';
    } else if (STREAM_TYPE === 'file' && AUDIO_FILE_URL) {
        //WaveSurfer Audio Player for uploaded file streams
        ytPlayer.style.display = 'none';
        const audioPlayerContainer = document.getElementById('audio-player-container');
        audioPlayerContainer.style.display = 'flex';
        audioPlayerContainer.style.flexDirection = 'column';
        audioPlayerContainer.style.alignItems = 'stretch';
        audioPlayerContainer.style.justifyContent = 'center';
        audioPlayerContainer.style.width = '100%';
        audioPlayerContainer.style.height = '100%';
        audioPlayerContainer.style.background = '#111827';
        audioPlayerContainer.style.borderRadius = '8px';
        audioPlayerContainer.style.padding = '24px';
        audioPlayerContainer.style.boxSizing = 'border-box';

        audioPlayerContainer.innerHTML = `
            <div style="display:flex; flex-direction:column; gap:16px; width:100%;">
                <div style="display:flex; align-items:center; gap:12px; color:#f3f4f6;">
                    <button id="ws-play-btn" style="width:48px;height:48px;border-radius:50%;background:#1d4ed8;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background 0.2s;">
                        <svg id="ws-play-icon" width="20" height="20" fill="white" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                        <svg id="ws-pause-icon" width="20" height="20" fill="white" viewBox="0 0 24 24" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                    </button>
                    <div style="flex:1; min-width:0;">
                        <p style="margin:0;font-size:0.8rem;color:#9ca3af;font-weight:500;">UPLOADED FILE</p>
                        <p style="margin:0;font-size:1rem;font-weight:600;color:#f3f4f6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">Audio File</p>
                    </div>
                    <span id="ws-time" style="font-size:0.85rem;color:#9ca3af;font-variant-numeric:tabular-nums;flex-shrink:0;">0:00 / 0:00</span>
                </div>
                <div id="ws-waveform" style="width:100%;border-radius:4px;overflow:hidden;"></div>
            </div>
        `;

        const ws = WaveSurfer.create({
            container: '#ws-waveform',
            waveColor: '#374151',
            progressColor: '#f97316',
            cursorColor: '#f97316',
            barWidth: 3,
            barGap: 2,
            barRadius: 2,
            height: 80,
            normalize: true,
            url: AUDIO_FILE_URL,
        });

        const playBtn = document.getElementById('ws-play-btn');
        const playIcon = document.getElementById('ws-play-icon');
        const pauseIcon = document.getElementById('ws-pause-icon');
        const timeDisplay = document.getElementById('ws-time');

        function formatTime(secs) {
            const m = Math.floor(secs / 60);
            const s = Math.floor(secs % 60).toString().padStart(2, '0');
            return `${m}:${s}`;
        }

        playBtn.addEventListener('click', () => ws.playPause());

        ws.on('play', () => {
            playIcon.style.display = 'none';
            pauseIcon.style.display = 'block';
            playBtn.style.background = '#1e40af';
            // Resume stream; transcripts flow again in sync with audio
            fileAudioPaused = false;
            connect();
        });
        ws.on('pause', () => {
            playIcon.style.display = 'block';
            pauseIcon.style.display = 'none';
            playBtn.style.background = '#1d4ed8';
            // Pause stream, stop receiving/rendering new chunks while audio is paused
            fileAudioPaused = true;
            if (wsSocket) {
                try { wsSocket.close(); } catch (_) {}
                wsSocket = null;
            }
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            statusText.innerText = 'Paused';
            pulseDot.classList.remove('connected');
        });
        ws.on('timeupdate', (currentTime) => {
            const duration = ws.getDuration();
            timeDisplay.textContent = `${formatTime(currentTime)} / ${formatTime(duration || 0)}`;
        });

    } else if (VIDEO_URL) {
        const ytId = extractYtId(VIDEO_URL);
        const twitchId = extractTwitchId(VIDEO_URL);
        const vimeoId = extractVimeoId(VIDEO_URL);
        
        if (ytId) {
            ytPlayer.src = `https://www.youtube.com/embed/${ytId}?autoplay=1&mute=1`;
        } else if (twitchId) {
            const currentHost = window.location.hostname;
            ytPlayer.src = `https://player.twitch.tv/?channel=${twitchId}&parent=${currentHost}&autoplay=true&muted=true`;
        } else if (vimeoId) {
            ytPlayer.src = `https://player.vimeo.com/video/${vimeoId}?autoplay=1&muted=1`;
        } else {
            console.info("Unrecognised URL — not a known streaming platform.");
            ytPlayer.style.display = 'none';
        }
    }


    // Streaming connection — WebSocket primary, SSE automatic fallback
    const captionsBox = document.getElementById('captions-box');
    const statusText = document.getElementById('connection-status');
    const pulseDot = document.querySelector('.pulse-dot');
    const langSelect = document.getElementById('viewer-lang-select');

    // Restore previously chosen language from localStorage (per-room preference)
    const savedLang = localStorage.getItem(`susi_lang_${TENANT_ID}`);
    if (savedLang && langSelect) langSelect.value = savedLang;

    let eventSource = null;   // active SSE connection (fallback)
    let wsSocket = null;       // active WebSocket connection (primary)
    let usingWebSocket = false;
    let lastChunkId = 0;

    // For file streams: block rendering while WaveSurfer is paused
    let fileAudioPaused = (STREAM_TYPE === 'file');

    // Audio State
    let playAudio = false;
    let audioQueue = [];
    let isPlaying = false;
    let currentAudio = null;
    let currentAudioId = null;

    function stopAndClearAudio() {
        audioQueue = [];
        isPlaying = false;
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
            currentAudioId = null;
        }
    }

    // Shared URL builders
    function buildQueryString(targetLang) {
        let qs = `tenant_id=${TENANT_ID}&source=${encodeURIComponent(STREAM_TYPE)}&last_chunk_id=${lastChunkId}&audio=${playAudio}`;
        if (!targetLang) targetLang = 'original';
        qs += `&target_lang=${encodeURIComponent(targetLang)}`;
        return qs;
    }

    function buildSseUrl(targetLang) {
        return `/api/v1/translate/stream?${buildQueryString(targetLang)}`;
    }

    function buildWsUrl(targetLang) {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${location.host}/ws/v1/translate/stream?${buildQueryString(targetLang)}`;
    }

    // Shared message handler used by BOTH WebSocket and SSE paths
    function handleMessage(data) {
        // Clear default placeholder on first real data
        const systemMsg = document.querySelector('.system-msg');
        if (systemMsg) systemMsg.remove();

        if (data.status === 'connected') return;

        if (data.status === 'error') {
            statusText.innerText = 'Stream Error';
            pulseDot.classList.remove('connected');
            pulseDot.classList.add('error');
            return;
        }

        // Track the highest chunk received for reconnect continuity
        const chunkInt = parseInt(data.chunk_id, 10);
        if (!isNaN(chunkInt) && chunkInt > lastChunkId) {
            lastChunkId = chunkInt;
        }

        // For file streams: drop renders when audio is paused to stay in sync
        if (fileAudioPaused) return;

        // Render transcript + translation blocks
        let block = document.getElementById(`chunk-${data.chunk_id}`);
        if (!block) {
            block = document.createElement('div');
            block.id = `chunk-${data.chunk_id}`;
            block.className = 'caption-block';

            const transcriptEl = document.createElement('p');
            transcriptEl.className = 'transcript-text';

            const translationEl = document.createElement('p');
            translationEl.className = 'translation-text';

            block.appendChild(transcriptEl);
            block.appendChild(translationEl);
            captionsBox.appendChild(block);
        }

        block.querySelector('.transcript-text').innerText = data.transcript;
        const translEl = block.querySelector('.translation-text');
        if (data.translation) {
            translEl.innerText = data.translation;
            translEl.style.display = '';
        } else {
            translEl.style.display = 'none';
        }

        // Push audio to queue if present
        if (playAudio && data.audio_b64) {
            const audioUrl = `data:audio/mp3;base64,${data.audio_b64}`;

            // Remove any pending audio in the queue for this exact chunk
            audioQueue = audioQueue.filter(item => item.id !== data.chunk_id);

            // If we are currently playing an older version of this exact chunk, stop it
            if (isPlaying && currentAudioId === data.chunk_id) {
                if (currentAudio) {
                    currentAudio.pause();
                    currentAudio.currentTime = 0;
                    currentAudio = null;
                }
                isPlaying = false;
            }

            audioQueue.push({ id: data.chunk_id, url: audioUrl });
            playNextAudio();
        }

        // Scroll to bottom
        captionsBox.scrollTop = captionsBox.scrollHeight;
    }

    // SSE fallback
    function connectSSE() {
        if (wsSocket) {
            try { wsSocket.close(); } catch (_) {}
            wsSocket = null;
        }
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        usingWebSocket = false;
        const targetLang = langSelect ? langSelect.value : '';
        statusText.innerText = 'Connecting (SSE)...';
        pulseDot.classList.remove('connected', 'error');

        const currentSse = new EventSource(buildSseUrl(targetLang), { withCredentials: true });
        eventSource = currentSse;

        currentSse.onopen = () => {
            statusText.innerText = (targetLang && langSelect)
                ? `Connected translating to ${langSelect.options[langSelect.selectedIndex].text}`
                : 'Connected transcript only';
            pulseDot.classList.add('connected');
        };

        currentSse.onmessage = (event) => {
            handleMessage(JSON.parse(event.data));
        };

        currentSse.onerror = () => {
            if (eventSource !== currentSse) return;
            statusText.innerText = 'Connection Lost Reconnecting...';
            pulseDot.classList.remove('connected');
            pulseDot.classList.add('error');
            // EventSource handles its own reconnect; no extra action needed here.
        };
    }

    // WebSocket primary transport
    function connectWebSocket() {
        if (wsSocket) {
            try { wsSocket.close(); } catch (_) {}
            wsSocket = null;
        }
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        const targetLang = langSelect ? langSelect.value : '';
        statusText.innerText = 'Connecting...';
        pulseDot.classList.remove('connected', 'error');

        // Guard: browsers that don't support WebSocket fall straight to SSE
        if (typeof WebSocket === 'undefined') {
            console.info('[stream] WebSocket not supported using SSE fallback');
            connectSSE();
            return;
        }

        let wsConnected = false; // tracks whether onopen fired before onerror/onclose

        let currentWs;
        try {
            currentWs = new WebSocket(buildWsUrl(targetLang));
            wsSocket = currentWs;
        } catch (err) {
            console.warn('[stream] WebSocket construction failed:', err, '— falling back to SSE');
            connectSSE();
            return;
        }

        currentWs.onopen = () => {
            wsConnected = true;
            usingWebSocket = true;
            statusText.innerText = (targetLang && langSelect)
                ? `Connected — translating to ${langSelect.options[langSelect.selectedIndex].text}`
                : 'Connected — transcript only';
            pulseDot.classList.add('connected');
        };

        currentWs.onmessage = (event) => {
            if (wsSocket !== currentWs) return;  // drop messages from superseded sockets
            try {
                handleMessage(JSON.parse(event.data));
            } catch (e) {
                console.error('[stream] WS message parse error:', e);
            }
        };

        currentWs.onerror = (err) => {
            console.warn('[stream] WebSocket error:', err);
            // onerror is always followed by onclose — handle fallback there
        };

        currentWs.onclose = (event) => {
            if (wsSocket !== currentWs) return;

            if (!wsConnected) {
                // The connection was never established — fall back to SSE immediately
                console.info('[stream] WebSocket upgrade failed (code', event.code, ') — falling back to SSE');
                wsSocket = null;
                connectSSE();
            } else {
                // Was connected, then lost — update status; browser will stay on
                // SSE if the user triggers a reconnect (language change / audio toggle).
                usingWebSocket = false;
                wsSocket = null;
                statusText.innerText = 'Connection Lost - Reconnecting...';
                pulseDot.classList.remove('connected');
                pulseDot.classList.add('error');
                // Automatically attempt one reconnect via SSE so captions are not lost
                console.info('[stream] WS dropped after connect (code', event.code, ') — reconnecting via SSE');
                connectSSE();
            }
        };
    }

    //always tries WS first, SSE fallback is automatic
    function connect() {
        connectWebSocket();
    }


    // Audio playback queue
    function playNextAudio() {
        if (isPlaying || audioQueue.length === 0) return;

        isPlaying = true;
        const nextItem = audioQueue.shift();
        currentAudioId = nextItem.id;
        currentAudio = new Audio(nextItem.url);

        currentAudio.onended = () => {
            isPlaying = false;
            currentAudio = null;
            currentAudioId = null;
            playNextAudio();
        };

        currentAudio.onerror = () => {
            console.error('Audio playback error');
            isPlaying = false;
            currentAudio = null;
            currentAudioId = null;
            playNextAudio();
        };

        currentAudio.play().catch(e => {
            console.error('Audio play blocked by browser:', e);
            isPlaying = false;
            currentAudio = null;
            currentAudioId = null;
            playNextAudio();
        });
    }

    // Initial connection
    if (STREAM_TYPE !== 'file') {
        connect();
    }
    // Reconnect when viewer picks a different language.
    if (langSelect) {
        langSelect.addEventListener('change', () => {
            stopAndClearAudio();
            
            const chosen = langSelect.value;
            localStorage.setItem(`susi_lang_${TENANT_ID}`, chosen);
            connect();
        });
    }

    // Download Button
    document.getElementById('download-btn').addEventListener('click', () => {
        let content = "Event Transcript and Translations\n";
        content += "===================================\n\n";

        const blocks = captionsBox.querySelectorAll('.caption-block');
        if (blocks.length === 0) {
            alert("No transcripts available to download yet.");
            return;
        }

        blocks.forEach(block => {
            const tx = block.querySelector('.transcript-text').innerText.trim();
            const tlEl = block.querySelector('.translation-text');
            const tl = tlEl && tlEl.style.display !== 'none' ? tlEl.innerText.trim() : null;

            if (tx) {
                content += `[Original]: ${tx}\n`;
                if (tl) {
                    content += `[Translated]: ${tl}\n`;
                }
                content += "\n";
            }
        });

        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const lang = (langSelect && langSelect.value) ? `_${langSelect.value}` : '';
        a.download = `susi_transcript_${TENANT_ID}${lang}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    // Audio Toggle Switch
    const audioToggleCheckbox = document.getElementById('audio-toggle-checkbox');
    const audioToggleLabel = document.getElementById('audio-toggle-label');

    if (audioToggleCheckbox && audioToggleLabel) {
        audioToggleCheckbox.addEventListener('change', (e) => {
            playAudio = e.target.checked;
            if (playAudio) {
                audioToggleLabel.innerText = 'TTS Active';
                audioToggleLabel.style.color = '#16a34a';
            } else {
                audioToggleLabel.innerText = 'TTS Muted';
                audioToggleLabel.style.color = '#5a6a8a';
                stopAndClearAudio(); // Clear queue on mute
            }
            connect(); // reconnect to inform backend to start/stop generating audio
        });
    }
});