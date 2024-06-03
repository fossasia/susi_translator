import pyaudio
import base64
import json
import requests
import time
import threading
import wave
from urllib3.util.retry import Retry
from urllib3.exceptions import MaxRetryError


# The AudioGrabber class initializes a PyAudio stream to capture audio from the microphone.
# The start method starts a separate thread to send audio chunks to the server.
# The send_audio method reads audio data from the stream, buffers it, and sends it to the server
# every 1 second.
# When the buffer reaches 20 seconds of audio, the send_chunk method is called to send the chunk
# to the server.
# The send_chunk method encodes the audio data with base64, creates a JSON payload with the chunk ID,
# and sends it to the server using requests.
# If the server responds with a 200 status

RATE = 16000
CHUNK_SIZE = RATE
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
BUFFER_SIZE = 2 * 10 * RATE  # 10 seconds of audio
SILENCE_THRESHOLD = 500
INPUT_DEVICE_INDEX = 1

class AudioGrabber:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(format=AUDIO_FORMAT,
                                      channels=CHANNELS,
                                      rate=RATE,
                                      input=True,
                                      input_device_index=INPUT_DEVICE_INDEX,
                                      frames_per_buffer=CHUNK_SIZE,
                                      stream_callback=self.audio_callback)
        self.buffer = bytearray()
        self.chunk_id = str(int(time.time() * 1000))
        self.send_thread = None
        self.recording = True

    def audio_callback(self, audio_data, frame_count, time_info, status):
        # Process the audio data here
        # print("callback audio size " + str(len(audio_data)))
        audio_sample = wave.struct.unpack("%dh" % (len(audio_data) / 2), audio_data)
        # if there is silence, we reset the buffer
        if (self.is_silent(audio_sample)):
            print("silence..")
            # we can reset the buffer here because we know that the current buffer has been send; its therefore the final buffer
            self.buffer = bytearray()  # Reset buffer
            self.chunk_id = str(int(time.time() * 1000)) # get new chunk ID: time in milliseconds
        else:
            print("audio extend")
            self.buffer.extend(audio_data)
            print("buffer audio size " + str(len(self.buffer)))

        # always send the buffern unless it's too small
        if len(self.buffer) > 0:
            print("send chunk")
            self.send_chunk()
        
        # in case that the buffer is too large, we start a new one. Then the previously send buffer was final
        if len(self.buffer) >= BUFFER_SIZE:
            self.buffer = bytearray()  # Reset buffer
            self.chunk_id = str(int(time.time() * 1000)) # get new chunk ID: time in milliseconds

        # Return the status code to continue the stream
        return audio_data, pyaudio.paContinue
    
    def start(self):
        self.send_thread = threading.Thread(target=self.send_audio)
        self.send_thread.start()

    def is_silent(self, data):
        m = max(data)
        print(str(m))
        return m < SILENCE_THRESHOLD

    def send_chunk(self):
        audio_b64 = base64.b64encode(self.buffer).decode('utf-8')
        data = {'chunk_id': self.chunk_id, 'audio_b64': audio_b64}
        try:
            retry_policy = Retry(total=5,  # Total number of retries
                         backoff_factor=1,  # Pause between retries in seconds
                         status_forcelist=[500, 502, 503, 504])  # Retry on these status codes
    
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_policy)
            session = requests.Session()
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            headers = {'Content-Type': 'application/json'}  # Ensure correct header
            response = session.post('http://localhost:5040/transcribe', json=data)
        
            if response.status_code == 200:
                print(f'Sent chunk {self.chunk_id} with {len(self.buffer)} bytes')
            else:
                print(f'Error sending chunk: {response.status_code}:{response.text}')
        except MaxRetryError as e:
            print(f'Error: Maximum retries exceeded. Could not connect to the endpoint.')
        except requests.exceptions.RequestException as e:
            print(f'Error sending chunk: {e}')

    def start(self):
        self.stream.start_stream()

    def stop(self):
        self.recording = False
        self.send_thread.join()
        self.stream.stop_stream()
        self.stream.close()
        self.audio.terminate()

if __name__ == '__main__':
    p = pyaudio.PyAudio()

    # Get the list of input devices
    device_count = p.get_device_count()
    for i in range(device_count):
        device_info = p.get_device_info_by_index(i)
        print(f"Device {i}: {device_info['name']}")

    grabber = AudioGrabber()
    grabber.start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        grabber.stop()
        print("Recording stopped by user")
