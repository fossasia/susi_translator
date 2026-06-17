function onStreamTypeChange() {
    const streamType = document.getElementById('stream-type').value;
    const streamInput = document.getElementById('stream-url');
    const streamInputLabel = document.getElementById('stream-input-label');
    
    const streamInputGroup = document.getElementById('stream-input-group');
    const fileUploadGroup = document.getElementById('file-upload-group');
    const audioUpload = document.getElementById('audio-upload');
    
    if (streamType === 'youtube') {
        streamInputGroup.classList.remove('hidden');
        if(fileUploadGroup) fileUploadGroup.style.display = 'none';
        if(audioUpload) audioUpload.required = false;
        streamInputLabel.innerHTML = 'Stream URL <span class="required" id="stream-input-required">*</span>';
        streamInput.placeholder = 'https://www.youtube.com/watch?v=...';
        streamInput.required = true;
    } else if (streamType === 'url') {
        streamInputGroup.classList.remove('hidden');
        if(fileUploadGroup) fileUploadGroup.style.display = 'none';
        if(audioUpload) audioUpload.required = false;
        streamInputLabel.innerHTML = 'Stream URL <span class="required" id="stream-input-required">*</span>';
        streamInput.placeholder = 'https://example.com/stream.m3u8';
        streamInput.required = true;
    } else if (streamType === 'file') {
        streamInputGroup.classList.add('hidden');
        streamInput.required = false;
        if(fileUploadGroup) fileUploadGroup.style.display = 'block';
        if(audioUpload) audioUpload.required = true;
    } else if (streamType === 'mic') {
        streamInputGroup.classList.add('hidden');
        if(fileUploadGroup) fileUploadGroup.style.display = 'none';
        if(audioUpload) audioUpload.required = false;
        streamInput.required = false;
        streamInput.value = '';
    }
}

function toggleTranslation() {
    const checkbox = document.getElementById('translation-toggle');
    const section = document.getElementById('translation-section');
    if (checkbox.checked) {
        section.classList.remove('hidden');
    } else {
        section.classList.add('hidden');
    }
}

function onTranscriptionModelChange() {
    const model = document.getElementById('transcription-model').value;
    const apikeyGroup = document.getElementById('transcription-apikey-group');
    const whisperSizeGroup = document.getElementById('whisper-size-group');

    // Show API key field for any cloud API model (OpenAI, etc.)
    const needsApiKey = ['deepl', 'openai'].includes(model);
    apikeyGroup.classList.toggle('hidden', !needsApiKey);

    // Show model size only for local Whisper
    const isWhisperLocal = model === 'whisper_local';
    whisperSizeGroup.classList.toggle('hidden', !isWhisperLocal);

    // Update the API key label to reflect which service
    const label = apikeyGroup.querySelector('label');
    label.textContent = 'API Key / HF Token';
}

function onTranslationModelChange() {
    const model = document.getElementById('translation-model').value;
    const apikeyGroup = document.getElementById('translation-apikey-group');

    // DeepL needs an API key; local NLLB does not.
    const needsApiKey = ['deepl'].includes(model);
    apikeyGroup.classList.toggle('hidden', !needsApiKey);

    // Update the API key label to reflect which service
    const label = apikeyGroup.querySelector('label');
    label.textContent = 'API Key';
}

// --- API Key Visual Masking ---
// After the user pastes/types a key and moves away from the field,
// we replace the visible text with asterisks so someone looking over
// their shoulder can't read the key. The real key is kept in a data
// attribute and used during form submission.
function _maskKeyField(inputEl) {
    inputEl.addEventListener('blur', () => {
        const realVal = inputEl.value;
        // Only update if the field actually has a value and it's not currently showing the masked dots
        if (realVal && inputEl.dataset.masked !== 'true') {
            inputEl.dataset.realKey = realVal;
            inputEl.value = '●'.repeat(Math.min(realVal.length, 24));
            inputEl.dataset.masked = 'true';
        }
    });
    inputEl.addEventListener('focus', () => {
        if (inputEl.dataset.masked === 'true') {
            inputEl.value = inputEl.dataset.realKey || '';
            inputEl.dataset.masked = 'false';
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // Auto-redirect if the room was already configured (e.g. user pressed back button)
    // unless they explicitly arrived here via the Edit button.
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.has('edit')) {
        let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
        let room = rooms.find(r => r.tenant_id === TENANT_ID);
        if (room && room.configured) {
            window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(room.videoUrl || '')}&type=${room.streamType || 'youtube'}`);
            return;
        }
    }

    _maskKeyField(document.getElementById('transcription-apikey'));
    _maskKeyField(document.getElementById('translation-apikey'));
});


document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const streamType = document.getElementById('stream-type').value;
    let streamUrl = document.getElementById('stream-url').value.trim();
    
    try {
        const loadingOverlay = document.getElementById('loading-overlay');
        const submitBtn = document.querySelector('.start-btn');
        loadingOverlay.classList.remove('hidden');
        submitBtn.disabled = true;

        if (streamType === 'file') {
            const fileInput = document.getElementById('audio-upload');
            if (!fileInput || fileInput.files.length === 0) {
                loadingOverlay.classList.add('hidden');
                submitBtn.disabled = false;
                alert('Please select an audio file to upload.');
                return;
            }
            
            document.getElementById('loading-subtitle').innerText = "Uploading audio securely...";
            
            const formData = new FormData();
            formData.append('audio_file', fileInput.files[0]);
            
            const uploadRes = await fetch('/api/v1/translate/upload_file', {
                method: 'POST',
                body: formData
            });
            const uploadData = await uploadRes.json();
            
            if (uploadData.status === 'success') {
                streamUrl = uploadData.file_path; // Use the internal docker path
                document.getElementById('loading-subtitle').innerText = "Starting engine...";
            } else {
                loadingOverlay.classList.add('hidden');
                submitBtn.disabled = false;
                alert('File upload failed: ' + uploadData.message);
                return;
            }
        }

    const sourceLang = document.getElementById('source-lang').value;
    const transcriptionModel = document.getElementById('transcription-model').value;
    const modelSize = document.getElementById('model-size').value;
    const transcriptionApiKey = (() => {
        const el = document.getElementById('transcription-apikey');
        return el.dataset.realKey || el.value.trim();
    })();
    const translationEnabled = document.getElementById('translation-toggle').checked;

    // build transcription block
    const transcriptionBlock = {
        provider_name: transcriptionModel,
        config: { model_size: modelSize }
    };
    if (transcriptionApiKey) {
        transcriptionBlock.config.api_key = transcriptionApiKey;
    }

    // build configure payload
    const payload = {
        tenant_id: TENANT_ID,
        stream_type: streamType,
        stream_url: streamUrl,
        transcription: transcriptionBlock,
    };

    // add translation block only if enabled
    if (translationEnabled) {
        const translationModel = document.getElementById('translation-model').value;
        const translationApiKey = (() => {
            const el = document.getElementById('translation-apikey');
            return el.dataset.realKey || el.value.trim();
        })();

        // target_lang is intentionally omitted — each viewer selects their own
        // language from the stream room. source_lang tells the model what the
        // speaker is speaking; target is decided per viewer at SSE connection time.
        payload.translation = {
            provider_name: translationModel,
            source_lang: sourceLang,
            config: {}
        };
        if (translationApiKey) {
            payload.translation.config.api_key = translationApiKey;
        }
    }

        // Send the configuration to the server
        const response = await fetch('/api/v1/translate/configure', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.status === 'success') {
            // If models were already cached in memory, pipeline_ready comes back true
            // immediately — skip polling and redirect right now.
            if (data.pipeline_ready === true) {
                document.getElementById('loading-title').innerText = "Models Ready!";
                document.getElementById('loading-subtitle').innerText = "Entering Stream Room...";
                let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
                rooms = rooms.map(r => {
                    if (r.tenant_id === TENANT_ID) {
                        r.configured = true;
                        r.videoUrl = streamUrl;
                        r.streamType = streamType;
                    }
                    return r;
                });
                localStorage.setItem('susi_rooms', JSON.stringify(rooms));
                setTimeout(() => {
                    window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(streamUrl)}&type=${streamType}`);
                }, 400);
                return;
            }

            // Models are still loading — fall back to 1-second polling.
            let pollCount = 0;

            const MAX_POLLS = 30; // 30 seconds timeout
            const pollInterval = setInterval(async () => {
                pollCount++;
                if (pollCount > MAX_POLLS) {
                    clearInterval(pollInterval);
                    document.getElementById('loading-title').innerText = "Ready!";
                    document.getElementById('loading-subtitle').innerText = "Entering Stream Room...";
                    // Redirect anyway — models may be ready even if status returned slow
                    setTimeout(() => {
                        let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
                        rooms = rooms.map(r => {
                            if (r.tenant_id === TENANT_ID) {
                                r.configured = true;
                                r.videoUrl = streamUrl;
                                r.streamType = streamType;
                            }
                            return r;
                        });
                        localStorage.setItem('susi_rooms', JSON.stringify(rooms));
                        window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(streamUrl)}&type=${streamType}`);
                    }, 500);
                    return;
                }
                try {
                    const statusRes = await fetch(`/api/v1/translate/status/${TENANT_ID}`, {
                        credentials: 'same-origin',
                    });
                    const statusData = await statusRes.json();

                    if (statusData.status === 'ready') {
                        // 3. Models are loaded! Stop polling and redirect.
                        clearInterval(pollInterval);
                        document.getElementById('loading-title').innerText = "Models Loaded!";
                        document.getElementById('loading-subtitle').innerText = "Entering Stream Room...";
                        setTimeout(() => {
                            let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
                            rooms = rooms.map(r => {
                                if (r.tenant_id === TENANT_ID) {
                                    r.configured = true;
                                    r.videoUrl = streamUrl;
                                    r.streamType = streamType;
                                }
                                return r;
                            });
                            localStorage.setItem('susi_rooms', JSON.stringify(rooms));

                            window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(streamUrl)}&type=${streamType}`);
                        }, 500);
                    }
                } catch (err) {
                    console.error("Polling error", err);
                }
            }, 1000);

        } else {
            loadingOverlay.classList.add('hidden');
            submitBtn.disabled = false;
            alert('Configuration failed: ' + data.message);
        }
    } catch (error) {
        document.getElementById('loading-overlay').classList.add('hidden');
        document.querySelector('.start-btn').disabled = false;
        alert('Network Error: Could not reach the translation server.');
}
});