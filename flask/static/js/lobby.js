// Stored in localStorage so they persist on refresh
let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');

function renderRooms() {
    const grid = document.getElementById('rooms-grid');
    grid.innerHTML = '';

    if (rooms.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <p>No rooms yet, click <strong>+ Create Room</strong> to get started.</p>
            </div>`;
        return;
    }

    rooms.forEach((room, i) => {
        const initial = room.name ? room.name.charAt(0).toUpperCase() : 'R';
        const card = document.createElement('div');
        card.className = 'room-card';
        card.innerHTML = `
            <div class="room-card-banner">${initial}</div>
            <div class="room-card-body">
                <h3>${escapeHtml(room.name)}</h3>
                <p>ID: ${room.tenant_id.slice(0, 8)}…</p>
            </div>
            <div class="room-card-footer">
                <button class="view-btn" onclick="openRoom(event, '${room.tenant_id}')">Open →</button>
                <div class="footer-actions">
                    <button class="edit-btn" onclick="editRoom(event, '${room.tenant_id}')">Edit</button>
                    <button class="delete-btn" onclick="deleteRoom(event, '${room.tenant_id}')">Delete</button>
                </div>
            </div>
        `;
        card.onclick = () => {
            if (room.configured && room.streamType === 'mic') {
                window.location.href = `/stream/${room.tenant_id}?url=&type=mic`;
            } else if (room.configured && room.videoUrl) {
                window.location.href = `/stream/${room.tenant_id}?url=${encodeURIComponent(room.videoUrl)}`;
            } else {
                window.location.href = `/config/${room.tenant_id}`;
            }
        };
        grid.appendChild(card);
    });
}

function openRoom(event, tenant_id) {
    event.stopPropagation();
    let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
    let room = rooms.find(r => r.tenant_id === tenant_id);
    if (room && room.configured && room.streamType === 'mic') {
        window.location.href = `/stream/${tenant_id}?url=&type=mic`;
    } else if (room && room.configured && room.videoUrl) {
        window.location.href = `/stream/${tenant_id}?url=${encodeURIComponent(room.videoUrl)}`;
    } else {
        window.location.href = `/config/${tenant_id}`;
    }
}

function editRoom(event, tenant_id) {
    event.stopPropagation();
    window.location.href = `/config/${tenant_id}?edit=true`;
}

function createRoom() {
    document.getElementById('roomName').value = '';
    const modal = document.getElementById('createModal');
    modal.style.display = 'flex';
    setTimeout(() => document.getElementById('roomName').focus(), 50);
}

function closeModal() {
    document.getElementById('createModal').style.display = 'none';
}

async function submitRoom() {
    const name = document.getElementById('roomName').value.trim();
    if (!name) {
        document.getElementById('roomName').focus();
        return;
    }

    const btn = document.getElementById('submitRoomBtn');
    btn.disabled = true;
    btn.textContent = 'Creating…';

    try {
        const response = await fetch('/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: 'youtube' }),
            credentials: 'same-origin',
        });

        const data = await response.json();
        const tenant_id = data.tenant_id;

        rooms.push({ name, tenant_id });
        localStorage.setItem('susi_rooms', JSON.stringify(rooms));

        closeModal();
        renderRooms();
    } catch (err) {
        alert('Failed to create room. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create';
    }
}

async function deleteRoom(event, tenant_id) {
    event.stopPropagation();
    if (!confirm('Delete this room?')) return;
    
    // Stop the background process and clean up server memory
    try {
        await fetch(`/stop_event/${tenant_id}`, {
            method: 'POST',
            credentials: 'same-origin',
        });
    } catch (e) {
        console.error("Failed to stop background process", e);
    }
    
    rooms = rooms.filter(r => r.tenant_id !== tenant_id);
    localStorage.setItem('susi_rooms', JSON.stringify(rooms));
    renderRooms();
}

// Close modal on overlay click
document.getElementById('createModal').addEventListener('click', function(e) {
    if (e.target === this) closeModal();
});

// Enter key in modal
document.getElementById('roomName').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') submitRoom();
    if (e.key === 'Escape') closeModal();
});

function escapeHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Render on load
renderRooms();