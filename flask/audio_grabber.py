import pyaudio
import base64
import json
import requests
import time
import argparse

RATE = 16000
CHUNK = RATE
FORMAT = pyaudio.paInt16
CHANNELS = 1

def list_devices(audio):
    print("Available audio input devices:")
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        print(f"{i}: {info['name']}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='http://localhost:5040/transcribe')
    parser.add_argument('--device', type=int, default=None)
    args = parser.parse_args()

    audio = pyaudio.PyAudio()
    list_devices(audio)
    device_index = args.device if args.device is not None else int(input("Select input device index: "))

    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, input_device_index=device_index, frames_per_buffer=CHUNK)
    print("Recording... Press Ctrl+C to stop.")

    try:
        while True:
            frames = stream.read(CHUNK)
            audio_b64 = base64.b64encode(frames).decode('utf-8')
            chunk_id = str(int(time.time() * 1000))
            payload = {'audio': audio_b64, 'chunk_id': chunk_id}
            try:
                r = requests.post(args.server, json=payload, timeout=10)
                if r.ok:
                    print(f"Transcribed: {r.json().get('text')}")
                else:
                    print(f"Server error: {r.text}")
            except Exception as e:
                print(f"Error sending audio: {e}")
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

if __name__ == '__main__':
    main()
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
