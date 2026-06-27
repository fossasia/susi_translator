document.addEventListener('DOMContentLoaded', () => {
    const micContainer = document.getElementById('mic-container');
    if (!micContainer || STREAM_TYPE !== 'mic') return;

    let audioContext;
    let mediaStream;
    let scriptProcessor;
    let analyser;
    let buffer = [];
    let tempBuffer = [];
    let chunkId = Date.now().toString();
    let isRecording = false;

    const RATE = 16000;
    const CHUNK_SIZE = RATE; // 1 second aggregator for VAD
    const BUFFER_SIZE = 10 * RATE; // Max 10 seconds of audio per sentence
    const SILENCE_THRESHOLD = 500 / 32768; // ~0.0152 (matches python backend)

    const micWave1 = document.getElementById('mic-wave-1');
    const micWave2 = document.getElementById('mic-wave-2');
    const micIconBtn = document.getElementById('mic-icon-btn');
    const micPrompt = document.getElementById('mic-prompt');

    micIconBtn.addEventListener('click', async () => {
        if (isRecording) {
            stopStream();
            return;
        }
        if (micPrompt) {
            micPrompt.style.display = 'block';
            micPrompt.innerText = "Requesting permission...";
        }
        
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: RATE,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });
            startStream(stream);
        } catch (err) {
            console.error('Error accessing microphone', err);
            const sysMsg = document.querySelector('.system-msg');
            if (sysMsg) sysMsg.innerText = 'Microphone access denied. Please check browser permissions.';
            if (micPrompt) micPrompt.innerText = "Error: Permission Denied";
        }
    });

    function startStream(stream) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: RATE });
        mediaStream = stream;
        const mediaStreamSource = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);

        mediaStreamSource.connect(analyser);
        mediaStreamSource.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);
        scriptProcessor.onaudioprocess = processAudio;

        isRecording = true;
        if (micPrompt) micPrompt.style.display = 'none';
        
        const sysMsg = document.querySelector('.system-msg');
        if (sysMsg && (sysMsg.innerText.includes('Waiting') || sysMsg.innerText.includes('turned off'))) {
            sysMsg.innerText = 'Listening to web microphone...';
        }
        
        animateWaves();
    }

    function stopStream() {
        isRecording = false;
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
        if (audioContext) {
            audioContext.close();
            audioContext = null;
        }
        
        const sysMsg = document.querySelector('.system-msg');
        if (sysMsg) {
            sysMsg.innerText = 'Microphone turned off. Click mic to restart.';
        }
        
        if (micPrompt) {
            micPrompt.style.display = 'block';
            micPrompt.innerText = "Click mic to start";
        }
        
        // Reset wave visuals
        if (micWave1) {
            micWave1.style.transform = `translate(-50%, -50%) scale(0.5)`;
            micWave1.style.opacity = '0';
        }
        if (micWave2) {
            micWave2.style.transform = `translate(-50%, -50%) scale(0.5)`;
            micWave2.style.opacity = '0';
        }
    }

    function processAudio(event) {
        if (!isRecording) return;
        
        const audioData = event.inputBuffer.getChannelData(0);
        for (let i = 0; i < audioData.length; i++) {
            tempBuffer.push(audioData[i]);
        }
        
        // Wait until we accumulate 1 second of audio
        if (tempBuffer.length >= CHUNK_SIZE) {
            let maxVal = 0;
            for (let i = 0; i < tempBuffer.length; i++) {
                if (Math.abs(tempBuffer[i]) > maxVal) maxVal = Math.abs(tempBuffer[i]);
            }
            
            if (maxVal < SILENCE_THRESHOLD) {
                // Completely silent 1-second chunk -> Flush & start new chunk
                buffer = [];
                chunkId = Date.now().toString();
            } else {
                // Active audio -> Append to running buffer and send
                for (let i = 0; i < tempBuffer.length; i++) {
                    buffer.push(tempBuffer[i]);
                }
                sendChunk();
                
                // If sentence is getting too long (>10s), force cut
                if (buffer.length >= BUFFER_SIZE) {
                    buffer = [];
                    chunkId = Date.now().toString();
                }
            }
            tempBuffer = []; // reset 1-second aggregator
        }
    }

    function sendChunk() {
        const int16Array = new Int16Array(buffer.map(n => n * 32767));
        const audioBuffer = new Blob([int16Array.buffer], { type: 'audio/wav' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBuffer);
        
        // Capture the chunkId locally to prevent it from changing before onloadend fires
        const currentChunkId = chunkId;

        reader.onloadend = () => {
            const base64data = reader.result.split(',')[1];
            const data = { chunk_id: currentChunkId, audio_b64: base64data, tenant_id: TENANT_ID };
            
            fetch('/transcribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).catch(error => console.error('Error sending audio chunk:', error));
        };
    }

    function animateWaves() {
        if (!isRecording) return;

        const timeData = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(timeData);

        const volume = Math.sqrt(timeData.reduce((sum, value) => sum + Math.pow(value - 128, 2), 0) / timeData.length);
        
        const scale1 = 1 + (volume / 15);
        const scale2 = 1 + (volume / 25);
        
        const opacity1 = Math.min(1, volume / 10);
        const opacity2 = Math.min(0.7, volume / 15);

        if (micWave1) {
            micWave1.style.transform = `translate(-50%, -50%) scale(${scale1})`;
            micWave1.style.opacity = opacity1.toFixed(2);
        }
        if (micWave2) {
            micWave2.style.transform = `translate(-50%, -50%) scale(${scale2})`;
            micWave2.style.opacity = opacity2.toFixed(2);
        }

        requestAnimationFrame(animateWaves);
    }
});