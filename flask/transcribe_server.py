from flask import Flask, request, Response, jsonify, stream_with_context
from flask_restx import Api, Resource, fields
from flask_cors import CORS
import numpy as np
import threading
import requests
import logging
import yaml
from faster_whisper import WhisperModel
import base64
import queue
import torch
import json
import time
import os
# added for translation pipeline
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
# added for Redis storage
import redis
# added for WAV header wrapping when forwarding to whisper.cpp server
import io
import soundfile as sf
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger')
CORS(app, resources={r"/*": {"origins": "*"}})

# we either use a local in-code model or access a whisper.cpp server
use_whisper_server = os.getenv('WHISPER_SERVER_USE', 'false') == 'true'
#model_name = os.getenv('WHISPER_MODEL', 'tiny')     # 39M
#model_name = os.getenv('WHISPER_MODEL', 'base')     # 74M
model_fast_name = os.getenv('WHISPER_MODEL', 'small')    # 244M
model_smart_name = os.getenv('WHISPER_MODEL', 'medium')   # 769M
#model_name = os.getenv('WHISPER_MODEL', 'large-v3') # 1550M

# Detect hardware compatibility
device = os.getenv('WHISPER_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
logger.info(f"Hardware detection: using {device}")

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
    # faster-whisper uses compute_type instead of in_memory; int8 for cpu, float16 for cuda
    compute_type = 'float16' if device == 'cuda' else 'int8'
    if os.path.exists(os.path.join(models_path, model_fast_name)):
        model_fast = WhisperModel(model_fast_name, device=device, compute_type=compute_type, download_root=models_path)
    else:
        model_fast = WhisperModel(model_fast_name, device=device, compute_type=compute_type)
    if os.path.exists(os.path.join(models_path, model_smart_name)):
        model_smart = WhisperModel(model_smart_name, device=device, compute_type=compute_type, download_root=models_path)
    else:
        model_smart = WhisperModel(model_smart_name, device=device, compute_type=compute_type)

# load NLLB-200 translation model for multilingual support
# facebook/nllb-200-distilled-600M is used
nllb_model_name = os.getenv('NLLB_MODEL', 'facebook/nllb-200-distilled-600M')
nllb_tokenizer = AutoTokenizer.from_pretrained(nllb_model_name)
nllb_model = AutoModelForSeq2SeqLM.from_pretrained(nllb_model_name).to(device)
logger.info(f"NLLB-200 translation model loaded: {nllb_model_name}")

# In-memory storage for transcripts
# transcriptd is kept as fallback in case Redis is unavailable
transcriptd = {} # should be a dictionary of dictionaries; the key is the tenant_id and the value is a dictionary with the chunk_id as key and the transcript as value
audio_stack = queue.Queue() # is this a fifo queue? yes, it is, a FILO queue would be LifoQueue

# connect to Redis for persistent transcript storage with auto-expiry
# Redis replaces the clean_old_transcripts logic; TTL is set per key instead
redis_client = None
try:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    redis_client.ping()
    logger.info("Redis connection established")
except Exception:
    logger.warning("Redis unavailable, falling back to in-memory transcriptd dict")
    redis_client = None

# TTL for transcripts in Redis
REDIS_TRANSCRIPT_TTL = 2*60*60

# whisper language code to NLLB-200 language tag mapping
def load_lang_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lang_map.yaml')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('whisper_to_nllb_lang', {})

WHISPER_TO_NLLB_LANG = load_lang_config()

def nllb_translate(text, src_lang_whisper, tgt_lang_nllb):
    lang_map = load_lang_config()
    src_lang_nllb = lang_map.get(src_lang_whisper, 'eng_Latn')
    if src_lang_nllb == tgt_lang_nllb:
        return text
    nllb_tokenizer.src_lang = src_lang_nllb
    inputs = nllb_tokenizer(text, return_tensors='pt', padding=True).to(device)
    target_lang_id = nllb_tokenizer.convert_tokens_to_ids(tgt_lang_nllb)
    translated_tokens = nllb_model.generate(
        **inputs,
        forced_bos_token_id=target_lang_id,
        max_length=512
    )
    return nllb_tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]

def redis_store_transcript(tenant_id, chunk_id, original, translated, source_lang, target_lang):
    # store both original and translated transcript in Redis as a hash with auto-expiry
    key = f"transcript:{tenant_id}:{chunk_id}"
    redis_client.hset(key, mapping={
        'original': original,
        'translated': translated,
        'source_lang': source_lang,
        'target_lang': target_lang
    })
    redis_client.expire(key, REDIS_TRANSCRIPT_TTL)

def redis_get_transcript(tenant_id, chunk_id):
    # retrieve transcript hash from Redis for a given tenant_id and chunk_id
    key = f"transcript:{tenant_id}:{chunk_id}"
    return redis_client.hgetall(key)  # returns {} if key does not exist

def redis_list_transcript_keys(tenant_id):
    # list all chunk_ids stored in Redis for a given tenant_id
    # uses pattern scan instead of KEYS to avoid blocking in production
    pattern = f"transcript:{tenant_id}:*"
    return [k.split(":")[-1] for k in redis_client.scan_iter(pattern)]

# Process audio data
def process_audio():
    while True:
        tenant_id, chunk_id, audiob64, source_type = audio_stack.get()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        # Skip forward in the stack until we find the last entry with the same chunk_id and the same tenant_id
        try:
            # scan through the whole audio_stack to find any other entries with the same chunk_id and tenant_id
            # in case we find one, we skip the head and take the next one from the head of the queue and scan again
            while audio_stack.qsize() > 0:
                foundSameChunk = False

                try:
                    for i in range(audio_stack.qsize()):
                        next_tenant_id, next_chunk_id, next_audiob64, next_source_type = audio_stack.queue[i]
                        if next_tenant_id == tenant_id and next_chunk_id == chunk_id:
                            # we found one entry with the same chunk_id and tenant_id which means we skip the head
                            foundSameChunk = True
                            break # breaks the for loop
                    if not foundSameChunk: break # breaks the while loop in case we did NOT found any other entry with the same chunk_id and tenant_id
                    # now we want to skip the head which means we load another head from the queue
                    tenant_id, chunk_id, audiob64, source_type = audio_stack.get()
                except IndexError:
                    break

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

            # faster-whisper takes numpy float32 array directly; no torch tensor conversion needed

            # Transcribe the audio data using the Whisper model
            #print("start to transcribe ...")

            # measure the time it takes to transcribe
            #start_time = time.time()
            # transcribe with a model according to stack size
            if audio_stack.qsize() > 20:
                #logger.info(f"using fast transcribe, stack size = {audio_stack.qsize()}")
                if use_whisper_server:
                    # make a http request to the whisper_server in the following way:
                    # curl whisper_server/inference -H "Content-Type: multipart/form-data" -F file="@<file-path>" -F response_format="json"
                    # wrap raw float32 PCM into a proper WAV buffer before sending to whisper.cpp server
                    # sending raw numpy bytes without a WAV header causes silent failures or garbage output
                    wav_buffer = io.BytesIO()
                    sf.write(wav_buffer, audio_array, samplerate=16000, format='WAV', subtype='PCM_16')
                    wav_buffer.seek(0)
                    files = {'file': ('audio.wav', wav_buffer, 'audio/wav')}
                    data = {'response_format': 'json'}
                    response = requests.post(whisper_server + '/inference', files=files, data=data)
                    
                else:
                    # faster-whisper transcribe returns (segments, info); join segments for full text
                    segments, info = model_fast.transcribe(audio_array, temperature=0, beam_size=5)
                    result = {'text': ' '.join(s.text for s in segments), 'language': info.language}
            else:
                #logger.info(f"using smart transcribe, stack size = {audio_stack.qsize()}")
                # faster-whisper transcribe returns (segments, info); join segments for full text
                segments, info = model_smart.transcribe(audio_array, temperature=0, beam_size=5)
                result = {'text': ' '.join(s.text for s in segments), 'language': info.language}
            #print("... finished transcribe")
            #print(f"transcribe time: {time.time() - start_time}")
            
            transcript = result['text'].strip()
            # detected_lang is provided by Whisper
            detected_lang = result.get('language', 'en')

            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")

                # translate the transcript using NLLB-200
                # target language is read per tenant from Redis config if available and defaults to English
                target_lang_nllb = 'eng_Latn'
                if redis_client:
                    tenant_config = redis_client.hgetall(f"tenant:{tenant_id}:config")
                    target_lang_nllb = tenant_config.get('target_lang', 'eng_Latn')
                translated_transcript = nllb_translate(transcript, detected_lang, target_lang_nllb)
                logger.info(f"TRANSLATED transcript for chunk_id {chunk_id}: {translated_transcript}")

                with threading.Lock():  # Ensure thread-safe access to shared resources
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    if redis_client:
                        # store both original and translated transcript in Redis with auto-expiry
                        redis_store_transcript(tenant_id, chunk_id, transcript, translated_transcript, detected_lang, target_lang_nllb)
                    else:
                        # fallback: store in in-memory transcriptd dict if Redis is unavailable
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
                            current_transcript['transcript'] = transcript
                            current_transcript['translated'] = translated_transcript
                        else:
                            # if the current transcript is None, we create a new entry with the new transcript
                            transcripts[chunk_id] = {'transcript': transcript, 'translated': translated_transcript}
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")
            
            # clean old transcripts to prevent memory bloat in case Redis is unavailable
            clean_old_transcripts()

        # Mark the task as done
        except Exception as e:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            audio_stack.task_done()

# Check if the transcript is valid: Contains at least one ASCII character and no forbidden words
def is_valid(transcript):
    transcript_lower = transcript.lower()
    # Check for at least one ASCII character with a code < 128 and code > 32 (we omit space in this case)
    has_ascii_char = any(ord(char) < 128 and ord(char) > 32 for char in transcript) 
    #has_ascii_char = any(ord(char) < 128 for char in transcript) 
    
    # Check for forbidden words (case insensitive)
    forbidden_phrases = {"thank you", "bye!", "thanks for watching", "click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)
    forbidden_strings = {"eh.", "you", "bye.", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # check if the transcript has words which are longer than 40 characters
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    # Return true only if both conditions are met
    return has_ascii_char and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words;

# Clean old transcripts: Remove all transcripts older than two hours
def clean_old_transcripts():
    # when Redis is active
    if redis_client:
        return
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)  # Two hours ago in milliseconds
    with threading.Lock():
        # make a list of tenant_ids to delete
        to_delete = []
        # iterate over all dictionaries in transcriptd
        for tenant_id in transcriptd.keys():
            transcripts = transcriptd[tenant_id]
            to_delete = [chunk_id for chunk_id in transcripts if int(chunk_id) < two_hours_ago]
            for chunk_id in to_delete:
                del transcripts[chunk_id]
            # its possible that the tenant_id has no more transcripts
            if len(transcripts) == 0:
                to_delete.append(tenant_id)
        
        # delete the tenant_ids
        for tenant_id in to_delete:
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
        # dict.keys() returns a view in Python 3, not a list. so we wrap with list() to allow index access
        last_key = list(transcripts.keys())[-1]
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
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000'),
    # source_type is sent by the updated AudioGrabber to indicate which AudioSource produced this chunk
    'source_type': fields.String(required=False, description='Audio source type: mic, file, or url', default='mic')
})

transcribe_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'tenant_id': fields.String(description='Tenant ID'),
    'status': fields.String(description='processing flag')
})

transcript_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text'),
    # translated field is returned alongside transcript when NLLB-200 translation is available
    'translated': fields.String(description='The translated text')
})

list_transcripts_response_model = api.model('ListTranscriptsResponse', {
    'transcripts': fields.List(fields.Nested(transcript_response_model), description='List of transcripts')
})

size_response_model = api.model('SizeResponse', {
    'size': fields.Integer(description='The number of transcripts')
})

def _push_to_queue(data, source_type):
    # shared helper to validate payload and push to audio_stack
    # source type is passed explicitly from each source-specific endpoint
    if not data:
        return {"error": "No JSON payload received"}, 400

    audio_b64 = data.get('audio_b64')
    chunk_id = data.get('chunk_id')
    tenant_id = data.get('tenant_id', '0000')

    if not audio_b64 or not chunk_id:
        return {"error": "Missing required fields"}, 400

    # push to processing queue with source type so process_audio can log the origin
    audio_stack.put((tenant_id, chunk_id, audio_b64, source_type))

    return {
        "chunk_id":chunk_id,
        "tenant_id": tenant_id,
        "status": "processing",
        "source_type": source_type
    }, 200

@api.route('/transcribe')
class Transcribe(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    @api.response(404, 'Transcript Not Found')
    def post(self):
        try:
            data = request.get_json(force=True)
            # source_type defaults to 'mic' for backward compatibility with old AudioGrabber
            source_type = data.get('source_type', 'mic') if data else 'mic'
            return _push_to_queue(data, source_type)
        except Exception as e:
            logger.error("Error in /transcribe", exc_info=True)
            return {"error": str(e)}, 500

# source-specific endpoints added to match the new AudioGrabber routing
# AudioGrabber now posts to /transcribe/{source_type} depending on which AudioSource is active

@api.route('/transcribe/mic')
class TranscribeMic(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    def post(self):
        # endpoint for MicrophoneSource chunks from the new AudioGrabber
        try:
            data = request.get_json(force=True)
            return _push_to_queue(data, 'mic')
        except Exception as e:
            logger.error("Error in /transcribe/mic", exc_info=True)
            return {"error": str(e)}, 500

@api.route('/transcribe/file')
class TranscribeFile(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    def post(self):
        # endpoint for FileSource chunks (.wav, .mp3) from the new AudioGrabber
        try:
            data = request.get_json(force=True)
            return _push_to_queue(data, 'file')
        except Exception as e:
            logger.error("Error in /transcribe/file", exc_info=True)
            return {"error": str(e)}, 500

@api.route('/transcribe/url')
class TranscribeURL(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    def post(self):
        # endpoint for URLSource chunks from the new AudioGrabber
        try:
            data = request.get_json(force=True)
            return _push_to_queue(data, 'url')
        except Exception as e:
            logger.error("Error in /transcribe/url", exc_info=True)
            return {"error": str(e)}, 500

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
        chunk_id = request.args.get('chunk_id')

        # fetch from Redis if available or, fall back to in memory transcriptd
        if redis_client:
            entry = redis_get_transcript(tenant_id, chunk_id)
            if entry:
                return jsonify({'chunk_id': chunk_id, 'transcript': entry.get('original', ''), 'translated': entry.get('translated', '')})
            else:
                return jsonify({'chunk_id': chunk_id, 'transcript': '', 'translated': ''})

        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true': t = merge_and_split_transcripts(t)
            if chunk_id in t:
                return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript'], 'translated': t[chunk_id].get('translated', '')})
            else:
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
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true': t = merge_and_split_transcripts(t)
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
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true': t = merge_and_split_transcripts(t)
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
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true': t = merge_and_split_transcripts(t)
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
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false') == 'true'
            if sentences == 'true': t = merge_and_split_transcripts(t)
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
        chunk_id = request.args.get('chunk_id')

        # delete from Redis if available; fall back to in-memory transcriptd
        if redis_client:
            key = f"transcript:{tenant_id}:{chunk_id}"
            entry = redis_client.hgetall(key)
            redis_client.delete(key)
            return jsonify({'chunk_id': chunk_id, 'transcript': entry.get('original', '')})

        t = transcriptd.get(tenant_id, {})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences == 'true': t = merge_and_split_transcripts(t)
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
        fromid = request.args.get('from', default='0')
        untilid = request.args.get('until', default=str(int(time.time() * 1000)))

        # fetch all chunk_ids from Redis and filter by from/until range
        if redis_client:
            chunk_ids = redis_list_transcript_keys(tenant_id)
            result = {}
            for chunk_id in chunk_ids:
                if int(fromid) <= int(chunk_id) <= int(untilid):
                    result[chunk_id] = redis_get_transcript(tenant_id, chunk_id)
            return jsonify(result)

        t = transcriptd.get(tenant_id, {})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences == 'true': t = merge_and_split_transcripts(t)
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
        fromid = request.args.get('from', default='0')
        untilid = request.args.get('until', default=str(int(time.time() * 1000)))

        # count matching chunk_ids from Redis if available
        if redis_client:
            chunk_ids = redis_list_transcript_keys(tenant_id)
            count = sum(1 for k in chunk_ids if int(fromid) <= int(k) <= int(untilid))
            return jsonify({'size': count})

        t = transcriptd.get(tenant_id, {})
        sentences = request.args.get('sentences', default='false') == 'true'
        if sentences == 'true': t = merge_and_split_transcripts(t)
        t = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
        return jsonify({'size': len(t)})

# set language config endpoint which allows frontend or admin to set source/target language per tenant
@api.route('/set_language_config')
class SetLanguageConfig(Resource):
    @api.doc(params={
        'tenant_id'  : {'description': 'Tenant ID', 'default': '0000'},
        'source_lang': {'description': 'Source language code (Whisper format e.g. de, fr)', 'default': 'en'},
        'target_lang': {'description': 'Target language NLLB BCP-47 tag e.g. eng_Latn', 'default': 'eng_Latn'}
    })
    @api.response(200, 'Success')
    def post(self):
        '''
        set source and target language for a given tenant_id; used by NLLB-200 translation pipeline
        '''
        tenant_id = request.args.get('tenant_id', '0000')
        source_lang = request.args.get('source_lang', 'en')
        target_lang = request.args.get('target_lang', 'eng_Latn')
        if redis_client:
            redis_client.hset(f"tenant:{tenant_id}:config", mapping={
                'source_lang': source_lang,
                'target_lang': target_lang
            })
            return jsonify({'tenant_id': tenant_id, 'source_lang': source_lang, 'target_lang': target_lang})
        return {"error": "Redis unavailable; language config requires Redis"}, 503

if __name__ == '__main__':
    # Start the audio processing thread
    threading.Thread(target=process_audio).start()

    # start the server
    app.run(host='0.0.0.0', port=5040, debug=False, use_reloader=False)