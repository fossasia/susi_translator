from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS
import whisper
import base64
import json
import numpy as np
import threading
import queue
import torch

# The /transcribe endpoint expects a stream of JSON objects with base64-encoded audio binaries.
# Each chunk should have a unique chunk_id.
# The server processes each chunk and transcribes the audio using Whisper.
# If the chunk_id is already present in the transcripts dictionary, the server updates
# the existing transcript by appending the new transcription. Otherwise, it starts a new transcript.
# The server returns a JSON response with the updated transcript for each chunk.

# The /get_transcript endpoint allows clients to retrieve the current transcript for a given chunk_id.
# If the chunk_id is not found, an empty transcript is returned.

app = Flask(__name__)
CORS(app)

# model = whisper.load_model("tiny") # 39M
model = whisper.load_model("base") # 74M
# model = whisper.load_model("small") # 244M
# model = whisper.load_model("medium") # 769M
# model = whisper.load_model("large") # 1550M
# model = whisper.load_model("large-v2") # 1550M

# In-memory storage for transcripts (you may want to use a database instead)
transcripts = {}
audio_stack = queue.Queue()

def process_audio():
    while True:
        audiob64, chunk_id = audio_stack.get()
        print("queue length: " + str(audio_stack.qsize()))
        # Skip forward in the stack until we find the last entry with the same chunk_id
        while True:
            try:
                next_audiob64, next_chunk_id = audio_stack.queue[0]
                if next_chunk_id != chunk_id:
                    break
                audiob64 = next_audiob64
                audio_stack.get_nowait()
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
            print(f"Empty audio array for chunk_id {chunk_id}")
            raise ValueError("Empty audio array")
            
        # Ensure no NaN values in audio array
        if np.isnan(audio_array).any():
            print(f"NaN values in audio array for chunk_id {chunk_id}")
            raise ValueError("NaN values in audio array")

        # Convert to PyTorch tensor
        audio_tensor = torch.from_numpy(audio_array)

        # Transcribe the audio data using the Whisper model
        print("start to transcribe ...")
        result = model.transcribe(audio_tensor)
        print("... finished transcribe")
        
        transcript = result['text']
        print(transcript)
        with threading.Lock():  # Ensure thread-safe access to shared resources
            if chunk_id in transcripts:
                transcripts[chunk_id]['transcript'] = transcript
            else:
                transcripts[chunk_id] = {'transcript': transcript}
        audio_stack.task_done()

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
                continue
    return Response(stream_with_context(generate_transcript()), content_type='text/event-stream')

@app.route('/get_transcript', methods=['GET'])
def get_transcript():
    chunk_id = request.args.get('chunk_id')
    if chunk_id in transcripts:
        return jsonify({'chunk_id': chunk_id, 'transcript': transcripts[chunk_id]['transcript']})
    else:
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@app.route('/get_first_transcript', methods=['GET'])
def get_first_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        latest_chunk_id = min(transcripts.keys())
        latest_transcript = transcripts[latest_chunk_id]['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/pop_first_transcript', methods=['GET'])
def pop_first_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        latest_chunk_id = min(transcripts.keys())
        latest_transcript = transcripts.pop(latest_chunk_id)['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/get_latest_transcript', methods=['GET'])
def get_latest_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        latest_chunk_id = max(transcripts.keys())
        latest_transcript = transcripts[latest_chunk_id]['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@app.route('/pop_latest_transcript', methods=['GET'])
def pop_latest_transcript():
    if len(transcripts) == 0:
        return jsonify({'chunk_id': '-1', 'transcript': ''})
    else:
        latest_chunk_id = max(transcripts.keys())
        latest_transcript = transcripts.pop(latest_chunk_id)['transcript']
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})
    
@app.route('/delete_transcript', methods=['GET'])
def delete_transcript():
    chunk_id = request.args.get('chunk_id')
    if chunk_id in transcripts:
        entry = transcripts.pop(chunk_id, None)
        return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
    else:
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@app.route('/list_transcripts', methods=['GET'])
def list_transcripts():
        return jsonify(transcripts)
    
@app.route('/transcripts_size', methods=['GET'])
def transcripts_size():
        return jsonify({'size': len(transcripts)})

if __name__ == '__main__':
    # Start the audio processing thread
    threading.Thread(target=process_audio).start()

    # start the server
    app.run(debug=True)
