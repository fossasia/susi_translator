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
            console.error("Invalid Video URL provided");
            ytPlayer.parentElement.innerHTML = '<div style="padding: 40px; text-align: center; color: #ef4444;">Invalid Video URL. Cannot load video.</div>';
        }
    }

    // SSE Connection — viewer-driven, reconnects when language changes
    const captionsBox = document.getElementById('captions-box');
    const statusText = document.getElementById('connection-status');
    const pulseDot = document.querySelector('.pulse-dot');
    const langSelect = document.getElementById('viewer-lang-select');

    // Restore previously chosen language from localStorage (per-room preference)
    const savedLang = localStorage.getItem(`susi_lang_${TENANT_ID}`);
    if (savedLang) langSelect.value = savedLang;

    let eventSource = null;
    let lastChunkId = 0;
    
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

    function buildSseUrl(targetLang) {
        let url = `/api/v1/translate/stream?tenant_id=${TENANT_ID}&source=youtube&last_chunk_id=${lastChunkId}&audio=${playAudio}`;
        if (targetLang) url += `&target_lang=${encodeURIComponent(targetLang)}`;
        return url;
    }

    function connect() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        const targetLang = langSelect.value;
        statusText.innerText = 'Connecting...';
        pulseDot.classList.remove('connected', 'error');

        eventSource = new EventSource(buildSseUrl(targetLang), { withCredentials: true });

        eventSource.onopen = () => {
            statusText.innerText = targetLang
                ? `Connected — translating to ${langSelect.options[langSelect.selectedIndex].text}`
                : 'Connected — transcript only';
            pulseDot.classList.add('connected');
        };

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

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

            // Track the highest chunk we've received for reconnect continuity
            const chunkInt = parseInt(data.chunk_id, 10);
            if (!isNaN(chunkInt) && chunkInt > lastChunkId) {
                lastChunkId = chunkInt;
            }

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
                
                // Add the new updated audio to the end of the queue
                audioQueue.push({ id: data.chunk_id, url: audioUrl });
                playNextAudio();
            }

            // Scroll to bottom
            captionsBox.scrollTop = captionsBox.scrollHeight;
        };

        eventSource.onerror = () => {
            statusText.innerText = 'Connection Lost - Reconnecting...';
            pulseDot.classList.remove('connected');
            pulseDot.classList.add('error');
        };
    }
    
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
            console.error("Audio playback error");
            isPlaying = false;
            currentAudio = null;
            currentAudioId = null;
            playNextAudio();
        };
        
        currentAudio.play().catch(e => {
            console.error("Audio play blocked by browser:", e);
            isPlaying = false;
            currentAudio = null;
            currentAudioId = null;
            playNextAudio();
        });
    }

    // 1. Initial Connection
    connect();

    // Reconnect when viewer picks a different language.
    // We keep lastChunkId so they don't re-receive all old chunks.
    // We no longer clear the screen, so past transcriptions are preserved.
    langSelect.addEventListener('change', () => {
        stopAndClearAudio();
        const chosen = langSelect.value;
        localStorage.setItem(`susi_lang_${TENANT_ID}`, chosen);
        
        // Removed captionsBox.innerHTML clear so past transcripts remain
        
        connect();
    });

    // 5. Download Button
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
        const lang = langSelect.value ? `_${langSelect.value}` : '';
        a.download = `room_${TENANT_ID}_transcript${lang}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    //Audio Toggle Switch
    const audioToggleCheckbox = document.getElementById('audio-toggle-checkbox');
    const audioToggleLabel = document.getElementById('audio-toggle-label');
    
    if (audioToggleCheckbox && audioToggleLabel) {
        audioToggleCheckbox.addEventListener('change', (e) => {
            playAudio = e.target.checked;
            if (playAudio) {
                audioToggleLabel.innerText = '🔊 TTS Active';
                audioToggleLabel.style.color = '#16a34a'; // green
            } else {
                audioToggleLabel.innerText = '🔇 TTS Muted';
                audioToggleLabel.style.color = '#5a6a8a';
                stopAndClearAudio(); // Clear queue on mute
            }
            connect(); // reconnect to inform backend to start/stop generating audio
        });
    }
});