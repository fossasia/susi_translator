from flask import Flask, request, Response, jsonify, stream_with_context
from flask_restx import Api, Resource, fields
from flask_cors import CORS
from flask_sock import Sock
import numpy as np
import threading
import requests
import logging
import whisper
import base64
import queue
import torch
import json
import time
import os

from websocket_manager import emit_stream_update

from stt_config import STT_NUM_WORKERS, STT_MAX_QUEUE_SIZE, STT_QUEUE_OVERFLOW_POLICY
from stt_ingest import try_enqueue

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger')
CORS(app, resources={r"/*": {"origins": "*"}})
sock = Sock(app)

_worker_started = False
_worker_lock = threading.Lock()


def ensure_process_audio_thread():
    """Start the STT worker pool once (HTTP + WebSocket ingestion)."""
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        for i in range(STT_NUM_WORKERS):
            threading.Thread(
                target=process_audio,
                name=f"stt-worker-{i}",
                daemon=True,
            ).start()
        _worker_started = True
        logger.info(
            "STT workers started: num=%s max_queue=%s overflow_policy=%s "
            "(set STT_NUM_WORKERS=1 if your Whisper backend is not thread-safe)",
            STT_NUM_WORKERS,
            STT_MAX_QUEUE_SIZE,
            STT_QUEUE_OVERFLOW_POLICY,
        )


@app.before_request
def _ensure_stt_worker():
    ensure_process_audio_thread()


# we either use a local in-code model or access a whisper.cpp server
use_whisper_server = os.getenv('WHISPER_SERVER_USE', 'false') == 'true'
#model_name = os.getenv('WHISPER_MODEL', 'tiny')     # 39M
#model_name = os.getenv('WHISPER_MODEL', 'base')     # 74M
model_fast_name = os.getenv('WHISPER_MODEL', 'small')    # 244M
model_smart_name = os.getenv('WHISPER_MODEL', 'medium')   # 769M
#model_name = os.getenv('WHISPER_MODEL', 'large-v3') # 1550M

if use_whisper_server:
    # Use the whisper.cpp server
    # this requires to start the server with the following command:
    # cd whisper.cpp
    # bash ./models/download-ggml-model.sh small
    # bash ./models/download-ggml-model.sh medium
    # bash ./models/download-ggml-model.sh large-v3
    # ./server -m models/ggml-medium.bin -l de -p 16 -t 32 --host 0.0.0.0 --port 8007
    # ./server -m models/ggml-large-v3.bin -l de -p 16 -t 32 --host 0.0.0.0 --port 8007
    whisper_server = os.getenv('WHISPER_SERVER', 'http://localhost:8007')
else:
    # Download a whisper model. If the download using the whisper library is not possible
    # i.e. if you are offline or behind a firewall, you can also use locally stored models.
    # To use a local model, download a model from the links as listed in
    # https://github.com/openai/whisper/blob/main/whisper/__init__.py#L17-L30


    script_dir = os.path.dirname(os.path.abspath(__file__))

    # load or download model
    # the possible model path is models_path + "/" + model_name + ".pt"
    # check if the model exists in the models_path
    models_path = os.path.join(script_dir, 'models')
    if os.path.exists(os.path.join(models_path, model_fast_name + ".pt")):
        model_fast = whisper.load_model(model_fast_name, in_memory=True, download_root=models_path)
    else:
        model_fast = whisper.load_model(model_fast_name, in_memory=True)
    if os.path.exists(os.path.join(models_path, model_smart_name + ".pt")):
        model_smart = whisper.load_model(model_smart_name, in_memory=True, download_root=models_path)
    else:
        model_smart = whisper.load_model(model_smart_name, in_memory=True)

# In-memory storage for transcripts
transcriptd = {} # should be a dictionary of dictionaries; the key is the tenant_id and the value is a dictionary with the chunk_id as key and the transcript as value
audio_stack = queue.Queue(maxsize=STT_MAX_QUEUE_SIZE)

_transcript_lock = threading.Lock()
_dequeue_coalesce_lock = threading.Lock()


def _unpack_audio_item(item):
    """Normalize to (tenant_id, chunk_id, audio_b64, session_id, enqueue_monotonic_ts)."""
    if isinstance(item, tuple) and len(item) == 5:
        return item[0], item[1], item[2], item[3], float(item[4])
    if isinstance(item, tuple) and len(item) == 4:
        t, c, a, s = item
        return t, c, a, s, time.monotonic()
    tenant_id, chunk_id, audiob64 = item
    return tenant_id, chunk_id, audiob64, None, time.monotonic()


def _queue_coalesce_key(entry):
    ln = len(entry)
    if ln >= 5:
        return entry[0], entry[1], entry[3]
    if ln == 4:
        return entry[0], entry[1], entry[3]
    return entry[0], entry[1], None


# Process audio data
def process_audio():
    while True:
        coalesced_gets = 0
        chunk_id = "-"
        session_id = None
        try:
            with _dequeue_coalesce_lock:
                item = audio_stack.get()
                coalesced_gets += 1
                tenant_id, chunk_id, audiob64, session_id, enqueue_ts = _unpack_audio_item(item)
                key = (tenant_id, chunk_id, session_id)
                logger.debug("STT dequeue qsize=%s key=%s", audio_stack.qsize(), key)
                # Drop superseded payloads: if a newer entry for the same key exists, advance to it.
                # Scan from the tail — duplicates from live streaming are usually near the end (O(1) typical).
                while audio_stack.qsize() > 0:
                    found_same = False
                    try:
                        n = audio_stack.qsize()
                        for i in range(n - 1, -1, -1):
                            next_entry = audio_stack.queue[i]
                            if _queue_coalesce_key(next_entry) == key:
                                found_same = True
                                break
                    except (IndexError, ValueError):
                        break
                    if not found_same:
                        break
                    tenant_id, chunk_id, audiob64, session_id, enqueue_ts = _unpack_audio_item(
                        audio_stack.get()
                    )
                    coalesced_gets += 1
                    key = (tenant_id, chunk_id, session_id)

            # Convert audio bytes to a writable NumPy array
            audio_data = base64.b64decode(audiob64)

            # Convert audio bytes to a writable NumPy array with int16 dtype
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # Convert int16 to float32 and normalize
            audio_array = audio_array.astype(np.float32) / 32768.0

            # Ensure the array is not empty
            if audio_array.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            # Ensure no NaN values in audio array
            if np.isnan(audio_array).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            # Convert to PyTorch tensor
            audio_tensor = torch.from_numpy(audio_array)

            if use_whisper_server:
                files = {'file': ('audio.wav', audio_array, 'application/octet-stream')}
                data = {'response_format': 'json'}
                response = requests.post(whisper_server, files=files, data=data)
                if response.status_code != 200:
                    logger.error(
                        "Whisper server error %s: %s",
                        response.status_code,
                        (response.text or "")[:200],
                    )
                    continue
                result = response.json()
                if not isinstance(result, dict) or "text" not in result:
                    logger.error("Unexpected whisper server JSON shape")
                    continue
            elif audio_stack.qsize() > 20:
                result = model_fast.transcribe(audio_tensor, temperature=0)
            else:
                result = model_smart.transcribe(audio_tensor, temperature=0)

            transcript = result["text"].strip()
            done_ts = time.monotonic()
            latency_ms = (done_ts - enqueue_ts) * 1000.0
            logger.info(
                "stt_latency_ms=%.1f chunk_id=%s session_id=%s qsize=%s workers=%s",
                latency_ms,
                chunk_id,
                session_id or "-",
                audio_stack.qsize(),
                STT_NUM_WORKERS,
            )
            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with _transcript_lock:
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    # get the current transcripts for the tenant_id
                    transcripts = transcriptd.get(tenant_id, None)
                    # if the current transcripts are None, we create a new dictionary for the tenant_id
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts

                    # get the current transcript for the chunk_id
                    current_transcript = transcripts.get(chunk_id, None)
                    # if the current transcript is not None, we append the new transcript to the current one
                    if current_transcript:
                        # here we do NOT append the new transcript to the current one becuase it is transcripted
                        # from the same audio data that has been transcripted before.
                        # The audio was appended by the client!
                        # We just overwrite the current transcript with the new one.
                        current_transcript["transcript"] = transcript
                    else:
                        # if the current transcript is None, we create a new entry with the new transcript
                        transcripts[chunk_id] = {"transcript": transcript}
                if session_id:
                    emit_stream_update(session_id, chunk_id, transcript, False)
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            # clean old transcripts
            clean_old_transcripts()

        except Exception as e:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            for _ in range(coalesced_gets):
                audio_stack.task_done()

# Check if the transcript is valid: no known hallucination phrases and no forbidden strings
def is_valid(transcript):
    transcript_lower = transcript.lower()

    forbidden_phrases = {"thanks for watching", "click, click", "click click", "cough cough"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "bye.", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # check if the transcript has words which are longer than 40 characters
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    return not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words

# Clean old transcripts: Remove all transcripts older than two hours
def clean_old_transcripts():
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)  # Two hours ago in milliseconds
    with _transcript_lock:
        tenants_to_remove = []
        for tenant_id in list(transcriptd.keys()):
            transcripts = transcriptd[tenant_id]
            old_chunks = [chunk_id for chunk_id in transcripts if int(chunk_id) < two_hours_ago]
            for chunk_id in old_chunks:
                del transcripts[chunk_id]
            if len(transcripts) == 0:
                tenants_to_remove.append(tenant_id)
        for tenant_id in tenants_to_remove:
            del transcriptd[tenant_id]

# merge all transcripts into one and split them into sentences
def merge_and_split_transcripts(transcripts):
    # Iterate through the sorted transcript keys.
    sec = ".!?"
    merged_transcripts = ""
    result = {}
    for key in transcripts.keys():
        if not merged_transcripts:
            # If merged_transcripts is empty, start with the first transcript.
            merged_transcripts += transcripts[key].strip()
        else:
            # Append the transcript to the merged string with a space and lowercase the following first character.
            t = transcripts[key].strip()
            if len(t) > 1:
                merged_transcripts += " " +  t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        # find first appearance of a sentence-ending character
        while any(char in sec for char in merged_transcripts):
            # split the merged transcript after the first sentence-ending character
            index = next(i for i, char in enumerate(merged_transcripts) if char in sec)
            # get head with sentence-ending character included
            head = merged_transcripts[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            p = result.get(key)
            if p:
                result[key] = p + " " + head
            else:
                result[key] = head
            
            # get tail without sentence-ending character
            merged_transcripts = merged_transcripts[index + 1:].strip()

    # add the last part of the merged transcript
    if merged_transcripts:
        last_key = transcripts.keys()[-1]
        p = result.get(last_key)
        if p:
            result[last_key] = p + " " + merged_transcripts
        else:
            result[last_key] = merged_transcripts

    return result

# Define models for API documentation
transcribe_input_model = api.model('Transcribe', {
    'audio_b64': fields.String(required=True, description='Base64 encoded audio data'),
    'chunk_id': fields.String(required=True, description='ID of the audio chunk'),
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000')
})

transcribe_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'tenant_id': fields.String(description='Tenant ID'),
    'status': fields.String(description='processing flag')
})

transcript_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text')
})

list_transcripts_response_model = api.model('ListTranscriptsResponse', {
    'transcripts': fields.List(fields.Nested(transcript_response_model), description='List of transcripts')
})

size_response_model = api.model('SizeResponse', {
    'size': fields.Integer(description='The number of transcripts')
})

@api.route('/transcribe')
class Transcribe(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    @api.response(404, 'Transcript Not Found')
    def post(self):
        '''
        The /transcribe endpoint expects a stream of JSON objects with base64-encoded audio binaries.
        Each chunk should have a unique chunk_id.
        The server processes each chunk and transcribes the audio using Whisper.
        '''
        def generate_transcript():
            while True:
                chunk = request.stream.read(2048000)
                if not chunk:
                    break
                try:
                    data = json.loads(chunk)
                    audio_b64 = data['audio_b64']
                    chunk_id = data['chunk_id']
                    tenant_id = data.get('tenant_id', '0000')
                    ok, err = try_enqueue(audio_stack, (tenant_id, chunk_id, audio_b64))
                    if ok:
                        response_data = {'chunk_id': chunk_id, 'tenant_id': tenant_id, 'status': 'processing'}
                    else:
                        response_data = {
                            'chunk_id': chunk_id,
                            'tenant_id': tenant_id,
                            'status': 'rejected',
                            'error': err or 'queue_full',
                        }
                    #print("queue length: " + str(audio_stack.qsize()))
                    #print("received chunk " + chunk_id + " with " + str(len(audio_b64)) + " bytes")
                    yield f"data: {json.dumps(response_data)}\n\n".encode('utf-8')
                except json.JSONDecodeError:
                    logger.error("JSON decode error", exc_info=True)
                    continue

        # Log request details
        #print(f"Request Headers: {request.headers}")
        #print(f"Request Method: {request.method}")
        #print(f"Request Body: {request.get_data()}")
        #logger.info(f"Received transcribe request with headers: {request.headers}")
        return Response(stream_with_context(generate_transcript()), content_type='text/event-stream')

@api.route('/get_transcript')
class GetTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'chunk_id' : {'description': 'Chunk ID'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        The /get_transcript endpoint allows clients to retrieve the transcript for a given chunk_id.
        If the chunk_id is not found, an empty transcript is returned.
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            chunk_id = request.args.get('chunk_id')
            if chunk_id in t:
                return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']})
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@api.route('/get_first_transcript')
class GetFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get first transcript endpoint: Retrieve the first transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            first_chunk_id = next((k for k in sorted(t.keys()) if int(k) >= int(fromid)), None)
            first_transcript = t[first_chunk_id]['transcript']
            return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@api.route('/pop_first_transcript')
class PopFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Pop first transcript endpoint: Retrieve and remove the first transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            first_chunk_id = next((k for k in sorted(t.keys()) if int(k) >= int(fromid)), None)
            first_transcript = t.pop(first_chunk_id)['transcript']
            return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@api.route('/get_latest_transcript')
class GetLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get latest transcript endpoint: Retrieve the latest transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            latest_chunk_id = next((k for k in sorted(t.keys(), reverse=True) if int(k) < int(untilid)), None)
            latest_transcript = t[latest_chunk_id]['transcript']
            return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@api.route('/pop_latest_transcript')
class PopLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get latest transcript endpoint: Retrieve and remove the latest transcript for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            if len(t) == 0:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            latest_chunk_id = next((k for k in sorted(t.keys(), reverse=True) if int(k) < int(untilid)), None)
            latest_transcript = t.pop(latest_chunk_id)['transcript']
            return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})
   
@api.route('/delete_transcript')
class DeleteTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        delete a transcript for a given tenant_id and chunk_id 
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            chunk_id = request.args.get('chunk_id')
            if chunk_id in t:
                entry = t.pop(chunk_id, None)
                return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@api.route('/list_transcripts')
class ListTranscripts(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', list_transcripts_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        list all transcripts for a given tenant_id
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            list = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
            return jsonify(list)
  
@api.route('/transcripts_size')
class TranscriptsSize(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', size_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        get the size of the transcripts for a given tenant_id  
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        with _transcript_lock:
            t = transcriptd.get(tenant_id, {})
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true':
                t = merge_and_split_transcripts(t)
            fromid = request.args.get('from', default='0')
            untilid = request.args.get('until', default=str(int(time.time() * 1000)))
            t = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
            return jsonify({'size': len(t)})


def get_transcript_for_ws(tenant_id: str, chunk_id: str) -> str:
    """Read current transcript text for finalize_chunk WebSocket control messages."""
    with _transcript_lock:
        row = transcriptd.get(tenant_id, {}).get(chunk_id)
    if isinstance(row, dict):
        return row.get("transcript", "") or ""
    return ""


@sock.route("/stt/stream")
def stt_stream(ws):
    """Real-time STT: send JSON audio messages; receive transcript events (see streaming_stt_ws)."""
    from streaming_stt_ws import run_stt_stream

    run_stt_stream(
        ws,
        request,
        enqueue_audio=lambda t, c, a, s: try_enqueue(audio_stack, (t, c, a, s)),
        ensure_worker=ensure_process_audio_thread,
        get_transcript=get_transcript_for_ws,
    )


if __name__ == '__main__':
    ensure_process_audio_thread()
    app.run(host='0.0.0.0', port=5055, debug=False)
