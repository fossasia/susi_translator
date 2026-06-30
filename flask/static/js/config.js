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
    const translationModel = document.getElementById('translation-model');
    
    if (checkbox.checked) {
        section.classList.remove('hidden');
        if (translationModel) translationModel.required = true;
    } else {
        section.classList.add('hidden');
        if (translationModel) translationModel.required = false;
    }
}

function onTranscriptionModelChange() {
    const model = document.getElementById('transcription-model').value;
    const whisperSizeGroup = document.getElementById('whisper-size-group');

    // Show model size only for local Whisper
    const isWhisperLocal = model === 'whisper_local';
    whisperSizeGroup.classList.toggle('hidden', !isWhisperLocal);
}

function onTranslationModelChange() {
    // No-op since we only use local models now
}



document.addEventListener('DOMContentLoaded', async () => {
    // Sync initial state of translation toggle
    toggleTranslation();

    // Auto-redirect if the room was already configured (e.g. user pressed back button)
    // unless they explicitly arrived here via the Edit button.
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.has('edit')) {
        try {
            const res = await fetch('/api/v1/translate/rooms', { credentials: 'same-origin' });
            if (res.ok) {
                const rooms = await res.json();
                const room = rooms.find(r => r.tenant_id === TENANT_ID);
                if (room && room.configured) {
                    window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(room.videoUrl || '')}&type=${room.streamType || 'youtube'}`);
                    return;
                }
            }
        } catch (e) {
            console.error("Failed to fetch rooms config check", e);
        }
    }


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
                headers: { 'X-CSRF-TOKEN': getCsrfToken() },
                credentials: 'same-origin',
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

    const translationEnabled = document.getElementById('translation-toggle').checked;

    // build transcription block
    const transcriptionBlock = {
        provider_name: transcriptionModel,
        config: { model_size: modelSize }
    };


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


        // target_lang is intentionally omitted — each viewer selects their own
        // language from the stream room. source_lang tells the model what the
        // speaker is speaking; target is decided per viewer at SSE connection time.
        payload.translation = {
            provider_name: translationModel,
            source_lang: sourceLang,
            config: {}
        };

    }

        // Send the configuration to the server
        const response = await fetch('/api/v1/translate/configure', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-TOKEN': getCsrfToken(),
            },
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