from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS
import whisper
import base64
import json
import numpy as np
import threading
import queue
import torch
import os
import logging
import time


# The /transcribe endpoint expects a stream of JSON objects with base64-encoded audio binaries.
# Each chunk should have a unique chunk_id.
# The server processes each chunk and transcribes the audio using Whisper.

# The /get_transcript endpoint allows clients to retrieve the current transcript for a given chunk_id.
# If the chunk_id is not found, an empty transcript is returned.

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Download a whisper model. If the download using the whisper library is not possible
# i.e. if you are offline or behind a firewall, you can also use locally stored models.
# To use a local model, download a model from the links as listed in
# https://github.com/openai/whisper/blob/main/whisper/__init__.py#L17-L30

#model_name = os.getenv('WHISPER_MODEL', 'tiny')     # 39M
#model_name = os.getenv('WHISPER_MODEL', 'base')     # 74M
model_name = os.getenv('WHISPER_MODEL', 'small')    # 244M
#model_name = os.getenv('WHISPER_MODEL', 'medium')   # 769M
#model_name = os.getenv('WHISPER_MODEL', 'large-v3') # 1550M
script_dir = os.path.dirname(os.path.abspath(__file__))

# load model and set mac GPU as device
try:
    model = whisper.load_model(model_name, in_memory=True)
except Exception as e:
    # load the model from the local model directory
    models_path = os.path.join(script_dir, 'models')
    model = whisper.load_model(model_name, in_memory=True, download_root=models_path)

#model.to('mps')

# In-memory storage for transcripts (you may want to use a database instead)
transcripts = {}
audio_stack = queue.Queue() # is this a fifo queue? yes, it is, a FILO queue would be LifoQueue

def process_audio():
    while True:
        audiob64, chunk_id = audio_stack.get()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        # Skip forward in the stack until we find the last entry with the same chunk_id
        try:
            while True:
                try:
                    next_audiob64, next_chunk_id = audio_stack.queue[0] # peek at the first element
                    if next_chunk_id != chunk_id: break
                    audiob64 = next_audiob64
                    audio_stack.get_nowait() # at least one element is in the queue
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

            # Convert to PyTorch tensor
            audio_tensor = torch.from_numpy(audio_array)

            # Transcribe the audio data using the Whisper model
            #print("start to transcribe ...")

            # measure the time it takes to transcribe
            #start_time = time.time()
            # transcribe
            result = model.transcribe(audio_tensor, temperature=0)
            #print("... finished transcribe")
            #print(f"transcribe time: {time.time() - start_time}")
            
            transcript = result['text'].strip()
            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with threading.Lock():  # Ensure thread-safe access to shared resources
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    # get the current transcript for the chunk_id
                    current_transcript = transcripts.get(chunk_id, None)
                    # if the current transcript is not None, we append the new transcript to the current one
                    if current_transcript:
                        # here we do NOT append the new transcript to the current one becuase it is transcripted
                        # from the same audio data that has been transcripted before.
                        # The audio was appended by the client!
                        # We just overwrite the current transcript with the new one.
                        current_transcript['transcript'] = transcript
                    else:
                        # if the current transcript is None, we create a new entry with the new transcript
                        transcripts[chunk_id] = {'transcript': transcript} 
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")
            
            # clean old transcripts
            clean_old_transcripts()

        # Mark the task as done
        except Exception as e:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            audio_stack.task_done()

def is_valid(transcript):
    # Check for at least one ASCII character with a code < 128 and code > 32 (we omit space in this case)
    # has_ascii_char = any(ord(char) < 128 and ord(char) > 32 for char in transcript) 
    has_ascii_char = any(ord(char) < 128 for char in transcript) 
    
    # Check for forbidden words (case insensitive)
    forbidden_words = {"thank", "you", "yeah"}
    transcript_lower = transcript.lower()
    contains_forbidden_words = any(word in transcript_lower for word in forbidden_words)
    
    # Return true only if both conditions are met
    return has_ascii_char and not contains_forbidden_words

def clean_old_transcripts():
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)  # Two hours ago in milliseconds
    with threading.Lock():
        to_delete = [chunk_id for chunk_id in transcripts if int(chunk_id) < two_hours_ago]
        for chunk_id in to_delete:
            del transcripts[chunk_id]

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

@app.route('/transcribe', methods=['POST'])
def transcribe():
    def generate_transcript():
        while True:
            chunk = request.stream.read(1024000)
            if not chunk:
                break
            try:
                data = json.loads(chunk)
                audio_b64 = data['audio_b64']
                chunk_id = data['chunk_id']
                audio_stack.put((audio_b64, chunk_id))
                #print("queue length: " + str(audio_stack.qsize()))
                response_data = {'chunk_id': chunk_id, 'status': 'processing'}
                #print("received chunk " + chunk_id + " with " + str(len(audio_b64)) + " bytes")
                yield f"data: {json.dumps(response_data)}\n\n".encode('utf-8')
            except json.JSONDecodeError:
                logger.error("JSON decode error", exc_info=True)
                continue

    # Log request details
    #print(f"Request Headers: {request.headers}")
    #print(f"Request Method: {request.method}")
    #print(f"Request Body: {request.get_data()}")
    
    logger.info(f"Received transcribe request")
    #logger.info(f"Received transcribe request with headers: {request.headers}")
    return Response(stream_with_context(generate_transcript()), content_type='text/event-stream')

@app.route('/get_transcript', methods=['GET'])
def get_transcript():
    chunk_id = request.args.get('chunk_id')
    sentences = request.args.get('sentences', default='false') == 'true'
    t = transcripts
    if sentences == 'true': t = merge_and_split_transcripts(transcripts)
    if chunk_id in t:
        return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']})
    else:
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@app.route('/get_first_transcript', methods=['GET'])
def get_first_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        sentences = request.args.get('sentences', default='false') == 'true'
        t = transcripts
        if sentences == 'true': t = merge_and_split_transcripts(transcripts)
        latest_chunk_id = min(t.keys())
        latest_transcript = t[latest_chunk_id]['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/pop_first_transcript', methods=['GET'])
def pop_first_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        sentences = request.args.get('sentences', default='false') == 'true'
        t = transcripts
        if sentences == 'true': t = merge_and_split_transcripts(transcripts)
        latest_chunk_id = min(t.keys())
        latest_transcript = t.pop(latest_chunk_id)['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/get_latest_transcript', methods=['GET'])
def get_latest_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        sentences = request.args.get('sentences', default='false') == 'true'
        t = transcripts
        if sentences == 'true': t = merge_and_split_transcripts(transcripts)
        latest_chunk_id = max(t.keys())
        latest_transcript = t[latest_chunk_id]['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/pop_latest_transcript', methods=['GET'])
def pop_latest_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        sentences = request.args.get('sentences', default='false') == 'true'
        t = transcripts
        if sentences == 'true': t = merge_and_split_transcripts(transcripts)
        latest_chunk_id = max(t.keys())
        latest_transcript = t.pop(latest_chunk_id)['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})
    
@app.route('/delete_transcript', methods=['GET'])
def delete_transcript():
    chunk_id = request.args.get('chunk_id')
    sentences = request.args.get('sentences', default='false') == 'true'
    t = transcripts
    if sentences == 'true': t = merge_and_split_transcripts(transcripts)
    if chunk_id in t:
        entry = t.pop(chunk_id, None)
        return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
    else:
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@app.route('/list_transcripts', methods=['GET'])
def list_transcripts():
    sentences = request.args.get('sentences', default='false') == 'true'
    t = transcripts
    if sentences == 'true': t = merge_and_split_transcripts(transcripts)
    return jsonify(t)
    
@app.route('/transcripts_size', methods=['GET'])
def transcripts_size():
    sentences = request.args.get('sentences', default='false') == 'true'
    t = transcripts
    if sentences == 'true': t = merge_and_split_transcripts(transcripts)
    return jsonify({'size': len(t)})

if __name__ == '__main__':
    # Start the audio processing thread
    threading.Thread(target=process_audio).start()

    # start the server
    app.run(host='0.0.0.0', port=5040, debug=True)
