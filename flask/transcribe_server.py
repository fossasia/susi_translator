from flask import Flask, request, Response, jsonify, stream_with_context
from flask_restx import Api, Resource, fields
from flask_cors import CORS
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

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger')
CORS(app, resources={r"/*": {"origins": "*"}})

# we either use a local in-code model or access a whisper.cpp server
use_whisper_server = os.getenv('WHISPER_SERVER_USE', 'false') == 'true'
model_fast_name = os.getenv('WHISPER_MODEL_FAST', 'small')    # 244M
model_smart_name = os.getenv('WHISPER_MODEL_SMART', 'medium') # 769M

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
    script_dir = os.path.dirname(os.path.abspath(__file__))
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
transcriptd = {}
audio_stack = queue.Queue()

# Process audio data
def process_audio():
    while True:
        tenant_id, chunk_id, audiob64 = audio_stack.get()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        try:
            while audio_stack.qsize() > 0:
                foundSameChunk = False
                try:
                    for i in range(audio_stack.qsize()):
                        next_tenant_id, next_chunk_id, next_audiob64 = audio_stack.queue[i]
                        if next_tenant_id == tenant_id and next_chunk_id == chunk_id:
                            foundSameChunk = True
                            break
                    if not foundSameChunk: break
                    tenant_id, chunk_id, audiob64 = audio_stack.get()
                except IndexError:
                    break

            # Decode audio
            audio_data = base64.b64decode(audiob64)

            # Fix: ensure even number of bytes for int16 conversion (fixes ValueError for odd length audio)
            if len(audio_data) % 2 != 0:
                audio_data = audio_data + b'\x00'

            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            audio_array = audio_array.astype(np.float32) / 32768.0

            if audio_array.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            if np.isnan(audio_array).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            audio_tensor = torch.from_numpy(audio_array)

            # Transcribe using whisper server or local model
            if use_whisper_server:
                # Fix: properly call whisper.cpp /inference endpoint and parse response
                try:
                    files = {'file': ('audio.wav', audio_array.tobytes(), 'audio/wav')}
                    data = {'response_format': 'json'}
                    response = requests.post(f"{whisper_server}/inference", files=files, data=data)
                    response.raise_for_status()
                    result_json = response.json()
                    transcript = result_json.get('text', '').strip()
                except Exception as e:
                    logger.error(f"Whisper server error for chunk_id {chunk_id}: {e}")
                    continue
            else:
                if audio_stack.qsize() > 20:
                    result = model_fast.transcribe(audio_tensor, temperature=0)
                else:
                    result = model_smart.transcribe(audio_tensor, temperature=0)
                transcript = result['text'].strip()

            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with threading.Lock():
                    transcripts = transcriptd.get(tenant_id, None)
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts
                    current_transcript = transcripts.get(chunk_id, None)
                    if current_transcript:
                        current_transcript['transcript'] = transcript
                    else:
                        transcripts[chunk_id] = {'transcript': transcript}
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            clean_old_transcripts()

        except Exception as e:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            audio_stack.task_done()


def is_valid(transcript):
    transcript_lower = transcript.lower()
    has_ascii_char = any(ord(char) < 128 and ord(char) > 32 for char in transcript)
    forbidden_phrases = {"thank you", "bye!", "thanks for watching", "click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "you", "bye.", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)
    contains_long_words = any(len(word) > 40 for word in transcript.split())
    return has_ascii_char and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words


def clean_old_transcripts():
    current_time = int(time.time() * 1000)
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)
    with threading.Lock():
        to_delete = []
        for tenant_id in transcriptd.keys():
            transcripts = transcriptd[tenant_id]
            to_delete = [chunk_id for chunk_id in transcripts if int(chunk_id) < two_hours_ago]
            for chunk_id in to_delete:
                del transcripts[chunk_id]
            if len(transcripts) == 0:
                to_delete.append(tenant_id)
        for tenant_id in to_delete:
            del transcriptd[tenant_id]


def merge_and_split_transcripts(transcripts):
    sec = ".!?"
    merged_transcripts = ""
    result = {}
    for key in transcripts.keys():
        if not merged_transcripts:
            merged_transcripts += transcripts[key].strip()
        else:
            t = transcripts[key].strip()
            if len(t) > 1:
                merged_transcripts += " " + t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        while any(char in sec for char in merged_transcripts):
            index = next(i for i, char in enumerate(merged_transcripts) if char in sec)
            head = merged_transcripts[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            p = result.get(key)
            if p:
                result[key] = p + " " + head
            else:
                result[key] = head
            merged_transcripts = merged_transcripts[index + 1:].strip()

    if merged_transcripts:
        last_key = list(transcripts.keys())[-1]
        p = result.get(last_key)
        if p:
            result[last_key] = p + " " + merged_transcripts
        else:
            result[last_key] = merged_transcripts

    return result


# API models
transcribe_input_model = api.model('Transcribe', {
    'audio_b64': fields.String(required=True, description='Base64 encoded audio data'),
    'chunk_id': fields.String(required=True, description='ID of the audio chunk'),
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000')
})

transcribe_response_model = api.model('TranscribeResponse', {
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
    @api.response(400, 'Bad Request')
    def post(self):
        '''
        Accepts audio chunks as regular JSON POST or as a streaming request.
        Supports both audio_grabber.py (JSON) and streaming clients.
        Validates required fields before processing.
        '''
        # Fix: Try regular JSON first (sent by audio_grabber.py)
        data = request.get_json(silent=True)
        if data:
            audio_b64 = data.get('audio_b64')
            chunk_id = data.get('chunk_id')
            tenant_id = data.get('tenant_id', '0000')

            # Fix: validate required fields and return 400 if missing
            if not audio_b64 or not chunk_id:
                return jsonify({'error': 'Missing required fields: audio_b64 and chunk_id'}), 400

            audio_stack.put((tenant_id, chunk_id, audio_b64))
            return jsonify({'chunk_id': chunk_id, 'tenant_id': tenant_id, 'status': 'processing'})

        # Fallback: handle streaming clients
        def generate_transcript():
            while True:
                chunk = request.stream.read(2048000)
                if not chunk:
                    break
                try:
                    data = json.loads(chunk)
                    audio_b64 = data.get('audio_b64')
                    chunk_id = data.get('chunk_id')
                    tenant_id = data.get('tenant_id', '0000')
                    if not audio_b64 or not chunk_id:
                        continue
                    audio_stack.put((tenant_id, chunk_id, audio_b64))
                    response_data = {'chunk_id': chunk_id, 'tenant_id': tenant_id, 'status': 'processing'}
                    yield f"data: {json.dumps(response_data)}\n\n".encode('utf-8')
                except json.JSONDecodeError:
                    logger.error("JSON decode error", exc_info=True)
                    continue

        return Response(stream_with_context(generate_transcript()), content_type='text/event-stream')


@api.route('/get_transcript')
class GetTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'chunk_id': {'description': 'Chunk ID'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Get transcript for a given chunk_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
        chunk_id = request.args.get('chunk_id')
        if chunk_id in t:
            return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']})
        else:
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})


@api.route('/get_first_transcript')
class GetFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from': {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Get first transcript for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
        fromid = request.args.get('from', default='0')
        first_chunk_id = next((k for k in sorted(t.keys()) if int(k) >= int(fromid)), None)
        first_transcript = t[first_chunk_id]['transcript']
        return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})


@api.route('/pop_first_transcript')
class PopFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from': {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Retrieve and remove the first transcript for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
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
    def get(self):
        '''Get latest transcript for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
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
    def get(self):
        '''Retrieve and remove the latest transcript for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
        untilid = request.args.get('until', default=str(int(time.time() * 1000)))
        latest_chunk_id = next((k for k in sorted(t.keys(), reverse=True) if int(k) < int(untilid)), None)
        latest_transcript = t.pop(latest_chunk_id)['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})


@api.route('/delete_transcript')
class DeleteTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'chunk_id': {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    def get(self):
        '''Delete a transcript for a given tenant_id and chunk_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        chunk_id = request.args.get('chunk_id')
        if chunk_id in t:
            entry = t.pop(chunk_id, None)
            return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
        else:
            return jsonify({'chunk_id': chunk_id, 'transcript': ''})


@api.route('/list_transcripts')
class ListTranscripts(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from': {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until': {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', list_transcripts_response_model)
    def get(self):
        '''List all transcripts for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
        fromid = request.args.get('from', default='0')
        untilid = request.args.get('until', default=str(int(time.time() * 1000)))
        result = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
        return jsonify(result)


@api.route('/transcripts_size')
class TranscriptsSize(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'from': {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until': {'description': 'End chunk ID', 'type': 'string', 'default': str(int(time.time() * 1000))}
    })
    @api.response(200, 'Success', size_response_model)
    def get(self):
        '''Get the number of transcripts for a given tenant_id'''
        tenant_id = request.args.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        fromid = request.args.get('from', default='0')
        untilid = request.args.get('until', default=str(int(time.time() * 1000)))
        t = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
        return jsonify({'size': len(t)})


if __name__ == '__main__':
    threading.Thread(target=process_audio, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)