disable_toc: true

<div id="header"></div>
<div id="transcript-container"></div>

<script>
  let transcriptContainer = document.getElementById('transcript-container');
  let pollingInProgress = false;  // Flag for serialized requests
  let lastChunkIds = [];  // Store the last 4 chunk IDs

  function adjustTranscriptContainerHeight() {
    const headerHeight = document.getElementById('header').offsetHeight;
    const windowHeight = window.innerHeight;
    transcriptContainer.style.height = (windowHeight - headerHeight - 80) + 'px';
  }

  function getParameterByName(name) {
    const url = window.location.href;
    const regex = new RegExp('[?&]' + name + '(=([^&#]*)|&|#|$)');
    const results = regex.exec(url);
    if (!results || !results[2]) return null;
    return decodeURIComponent(results[2].replace(/\+/g, ' '));
  }

  function getLatestTranscript() {
    if (pollingInProgress) {
      return;  // Skip if a request is already in progress
    }

    pollingInProgress = true;  // Set flag indicating polling has started

    tenant_id = getParameterByName('tenant_id'); // Get tenant_id from URL parameter
    if (!tenant_id) tenant_id = "0000"; // default id

    let get_latest_transcript_url = `/api/get_latest_transcript?tenant_id=${tenant_id}`;

    fetch(get_latest_transcript_url)
      .then(response => response.json())
      .then(data => {
        const chunk_ids = Object.keys(data);
        const currentChunks = [];

        for (let i = 0; i < chunk_ids.length; i++) {
          const chunk_id = chunk_ids[i];
          const transcript_event = data[chunk_id];
          const transcript = transcript_event.transcript;
          currentChunks.push({ chunk_id, transcript });
        }

        const lastChunks = currentChunks.slice(-4); // Keep only last 4 chunks

        // Determine if there is a new chunk

        const isNewChunk = lastChunks.some(chunk => !lastChunkIds.includes(chunk.chunk_id));

        if (isNewChunk) {
          // If more than 4 lines are in the container, remove the first (topmost) one
          if (transcriptContainer.children.length >= 4) {
            const firstLine = transcriptContainer.firstChild;
            const lineHeight = firstLine.offsetHeight;

            // Shift the container up by the height of one line
            transcriptContainer.style.transform = `translateY(-${lineHeight}px)`;

            // After the transition, remove the first line and reset the transform
            setTimeout(() => {
              transcriptContainer.removeChild(firstLine); // Remove after transition
              transcriptContainer.style.transform = 'translateY(0)'; // Reset transform
            }, 500); // Matches the CSS transition duration
          }

          // Append the new line
          const newChunk = lastChunks[lastChunks.length - 1];
          const newLine = document.createElement('div');
          newLine.classList.add('transcript-line');
          newLine.id = newChunk.chunk_id;
          newLine.textContent = newChunk.transcript;
          newLine.style.transform = 'translateY(0)'; // Start below the visible area
          transcriptContainer.appendChild(newLine);

          // Update lastChunkIds
          lastChunkIds = lastChunks.map(chunk => chunk.chunk_id);
        } else {
          // If no new chunk, still update existing lines if necessary
          lastChunks.forEach((chunk) => {
            let existingLine = document.getElementById(chunk.chunk_id);
            if (existingLine) {
              // Update the content if changed
              if (existingLine.textContent !== chunk.transcript) {
                existingLine.textContent = chunk.transcript;
              }
            }
          });
        }
      })

      .catch(error => console.error('Error fetching latest transcript:', error))
      .finally(() => {
        pollingInProgress = false;  // Reset the flag once polling is done

        // Schedule the next poll after this one is done
        setTimeout(getLatestTranscript, 1000);  // Poll every 1 second
      });
  }


  // Adjust transcript container height on load and resize
  window.addEventListener('load', () => {
    adjustTranscriptContainerHeight();
    getLatestTranscript();  // Start polling when the page loads
  });

  window.addEventListener('resize', adjustTranscriptContainerHeight);
</script>
