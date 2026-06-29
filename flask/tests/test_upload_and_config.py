import pytest
from io import BytesIO

def test_upload_file_unauthorized(unauth_client):
    """Ensure unauthenticated users cannot upload files."""
    resp = unauth_client.post('/api/v1/translate/upload_file', data={})
    assert resp.status_code == 401

def test_upload_file_invalid_extension(client):
    """Ensure invalid file extensions are blocked."""
    data = {
        'audio_file': (BytesIO(b"dummy data"), 'test.txt')
    }
    resp = client.post('/api/v1/translate/upload_file', data=data, content_type='multipart/form-data')
    assert resp.status_code == 415

def test_upload_file_too_large(client, ts):
    """Ensure files exceeding MAX_CONTENT_LENGTH are rejected."""
    # We set MAX_CONTENT_LENGTH dynamically for the test to avoid uploading 10MB
    original_size = ts.app.config.get('MAX_CONTENT_LENGTH')
    ts.app.config['MAX_CONTENT_LENGTH'] = 10  # 10 bytes limit
    
    data = {
        'audio_file': (BytesIO(b"this is more than 10 bytes"), 'test.mp3')
    }
    resp = client.post('/api/v1/translate/upload_file', data=data, content_type='multipart/form-data')
    
    # Restore size
    ts.app.config['MAX_CONTENT_LENGTH'] = original_size
    
    assert resp.status_code == 413

def test_transcripts_endpoint_requires_auth(unauth_client):
    """Ensure /transcripts endpoint correctly rejects unauthenticated posts."""
    resp = unauth_client.post('/transcripts', json={
        "tenant_id": "test_tenant",
        "audio_b64": "dummy",
        "chunk_id": "123"
    })
    # Will be 401 Unauthorized
    assert resp.status_code == 401

def test_configure_provider_bad_url_leaves_room_unconfigured(client, ts):
    """
    Ensure that a bad stream URL fails the configuration
    and does NOT modify the database room state or kill existing processes prematurely.
    """
    with ts.app.app_context():
        from auth.models import Room
        room = Room(tenant_id="test_tenant_bad", name="Test Room", organizer_id=1, configured=False)
        ts.db.session.add(room)
        ts.db.session.commit()

    resp = client.post('/api/v1/translate/configure', json={
        "tenant_id": "test_tenant_bad",
        "stream_type": "file",
        "stream_url": "/does/not/exist.mp3"
    })
    
    assert resp.status_code == 400
    
    # Check if room is still unconfigured
    with ts.app.app_context():
        from auth.models import Room
        room = ts.db.session.get(Room, "test_tenant_bad")
        assert room.configured is False
