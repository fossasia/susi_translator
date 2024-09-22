# transcribe_app/transcribe_utils.py
import os
import io
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
from scipy.io.wavfile import write as wav_write

logger = logging.getLogger(__name__)

# we either use a local in-code model or access a whisper.cpp server
use_whisper_server = os.getenv('WHISPER_SERVER_USE', 'true') == 'true'
#model_name = os.getenv('WHISPER_MODEL', 'tiny')     # 39M
#model_name = os.getenv('WHISPER_MODEL', 'base')     # 74M
model_fast_name = os.getenv('WHISPER_MODEL', 'small')    # 244M
model_smart_name = os.getenv('WHISPER_MODEL', 'medium')   # 769M
#model_name = os.getenv('WHISPER_MODEL', 'large-v3') # 1550M

translation_cache = {}
translation_ongoing = False

if use_whisper_server:
    # Use the whisper.cpp server
    # this requires to start the server with the following command:
    # cd whisper.cpp
    # bash ./models/download-ggml-model.sh small
    # bash ./models/download-ggml-model.sh medium
    # bash ./models/download-ggml-model.sh large-v3
    # ./server -m models/ggml-medium.bin -l de -p 16 -t 32 --host 0.0.0.0 --port 8007
    # ./server -m models/ggml-large-v3.bin -l de -p 16 -t 32 --host 0.0.0.0 --port 8007
    whisper_server = os.getenv('WHISPER_SERVER', 'https://whisper.susi.ai')
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
transcriptd = {} # dictionary of objects; the key is the chunk_id and the value is a dictionary with the chunk_id as key and the transcript as value
audio_stack = queue.Queue() # is this a fifo queue? yes, it is, a FILO queue would be LifoQueue

# Process audio data
def process_audio():
    while True:
        tenant_id, chunk_id, audiob64, translate_from, translate_to = audio_stack.get()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        # Skip forward in the stack until we find the last entry with the same chunk_id and the same tenant_id
        try:
            # scan through the whole audio_stack to find any other entries with the same chunk_id and tenant_id
            # in case we find one, we skip the head and take the next one from the head of the queue and scan again
            while audio_stack.qsize() > 0:
                foundSameChunk = False

                try:
                    for i in range(audio_stack.qsize()):
                        next_tenant_id, next_chunk_id, next_audiob64, next_translate_from, next_translate_to = audio_stack.queue[i]
                        if next_tenant_id == tenant_id and next_chunk_id == chunk_id:
                            # we found one entry with the same chunk_id and tenant_id which means we skip the head
                            foundSameChunk = True
                            break # breaks the for loop
                    if not foundSameChunk: break # breaks the while loop in case we did NOT found any other entry with the same chunk_id and tenant_id
                    # now we want to skip the head which means we load another head from the queue
                    tenant_id, chunk_id, audiob64, translate_from, translate_to = audio_stack.get()
                except IndexError:
                    break

            # Convert audio bytes to a writable NumPy array
            audio_data = base64.b64decode(audiob64)

            # Convert audio bytes to a writable NumPy array with int16 dtype
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
                
            # Ensure the array is not empty
            if audio_array.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue
                
            # Ensure no NaN values in audio array
            if np.isnan(audio_array).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            # Transcribe the audio data using the Whisper model
            #start_time = time.time()
            if use_whisper_server:
                if audio_array.dtype != np.int16:
                    # Resample the audio to 16kHz and 16-bit format (LEI16@16000)
                    audio_array = audio_array.astype(np.int16)  # Ensure 16-bit encoding

                # Create a buffer to hold the WAV file in memory
                wav_buffer = io.BytesIO()
                sample_rate = 16000
                wav_write(wav_buffer, sample_rate, audio_array)
                wav_buffer.seek(0)

                # Prepare the request to the whisper server
                files = {'file': ('audio.wav', wav_buffer, 'audio/wav')}
                data = {
                    'temperature': '0.0',
                    'temperature_inc': '0.0',
                    'response_format': 'json',
                }
                #response = requests.post(whisper_server, files=files, data=data)
                response = requests.post(f"{whisper_server}/inference", files=files, data=data)

                # json response is for example:
                # {
                #    "task": "transcribe",
                #    "language": "english",
                #    "duration": 2.999812602996826,
                #    "text": " How can a clam cram in a clean cream can?\n"
                # }
                # Check if the response was successful
                if response.status_code == 200:
                    # Parse the JSON response
                    json_response = response.json()
                    transcript = json_response.get('text', '').strip()
                else:
                    print(f"Error: {response.status_code}, {response.text}")
            else:
                # Convert int16 to float32 and normalize
                audio_array = audio_array.astype(np.float32) / 32768.0
                # Convert to PyTorch tensor
                audio_tensor = torch.from_numpy(audio_array)
                result = model_fast.transcribe(audio_tensor, temperature=0)            
                transcript = result.get('text', '').strip()
            #print("... finished transcribe")
            #print(f"transcribe time: {time.time() - start_time}")
            
            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with threading.Lock():  # Ensure thread-safe access to shared resources
                    # we must distinguish between the case where the chunk_id is already in the transcripts
                    # this can happen quite often because the client will generate a new chunk_id only when
                    # the recorded audio has silence. So all chunks are those pieces with speech without a pause.

                    # get the current transcripts for the tenant_id
                    transcripts = transcriptd.get(tenant_id, None)
                    # if the current transcripts are None, we create a new dictionary for the tenant_id
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts
                    
                    # check if transcripts has the chunk_id
                    transcript_event = transcripts.get(chunk_id)
                    if not transcript_event:
                        # here is the opportunity to translate the transcript of the latest chunk_id because it will now be fixed and not overwritten again
                        last_chunk_id1 = list(transcripts.keys())[-1] if len(transcripts) > 0 else None
                        last_chunk_id2 = list(transcripts.keys())[-2] if len(transcripts) > 1 else None
                        last_chunk_id3 = list(transcripts.keys())[-3] if len(transcripts) > 3 else None
                        
                        # the chunk_id is new and we start a new transcript event
                        transcript_event = {}
                        transcripts[chunk_id] = transcript_event
                        
                        translation_done = False
                        if not translation_ongoing and last_chunk_id3:
                            translation_done = process_translation(transcripts[last_chunk_id3])
                            
                        if not translation_ongoing and not translation_done and last_chunk_id2:
                            translation_done = process_translation(transcripts[last_chunk_id2])
                                
                        if not translation_ongoing and not translation_done and last_chunk_id1:
                            #process_translation(transcripts[last_chunk_id1])
                            threading.Thread(target=process_translation, args=(transcripts[last_chunk_id1],)).start()
                    
                    # Overwrite the transcript for this chunk_id
                    # here we do NOT append the new transcript to the current one becuase it is transcripted
                    # from the same audio data that has been transcripted before.
                    # The audio was appended by the client!
                    # We just overwrite the current transcript with the new one.
                    transcript_event = transcripts[chunk_id]
                    transcript_event['translated'] = False
                    transcript_event['transcript'] = transcript
                    transcript_event['translate_from'] = translate_from
                    transcript_event['translate_to'] = translate_to
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")
            
            # clean old transcripts
            clean_old_transcripts()

        # Mark the task as done
        except Exception as e:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            audio_stack.task_done()

def process_translation(transcript_event):
    translated = transcript_event.get('translated', False)
    translate_to = transcript_event.get('translate_to', '')
    
    # check if we have to translate the transcript event
    if not translate_to or translate_to == "_" or translated: return False
    
    # make the translation
    transcript_event['translated'] = True # mark the last transcript as translated early so no other thread will translate it as well
    translate_from = transcript_event.get('translate_from', '')
    transcript = transcript_event.get('transcript', '')
    translation = translate(transcript, translate_from, translate_to)
    transcript_event['transcript'] = translation
    transcript_event['original'] = transcript
    return True

# Check if the transcript is valid: Contains at least one ASCII character and no forbidden words
def is_valid(transcript):
    if not transcript: return False
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
    current_time = int(time.time() * 1000)  # Current time in milliseconds
    two_hours_ago = current_time - (2 * 60 * 60 * 1000)  # Two hours ago in milliseconds
    with threading.Lock():
        # make a list of tenant_ids to delete
        to_delete = []
        # iterate over all dictionaries in transcriptd
        for tenant_id in transcriptd.keys():
            transcripts = transcriptd[tenant_id]
            to_delete = [chunk_id for chunk_id in transcripts if int(chunk_id) < two_hours_ago]
            for chunk_id in to_delete: del transcripts[chunk_id]
            # its possible that the tenant_id has no more transcripts
            if len(transcripts) == 0: to_delete.append(tenant_id)
        
        # delete the tenant_ids
        for tenant_id in to_delete: transcriptd.pop(tenant_id, None)

def merge_and_split_transcripts(transcripts):
    return transcripts

# merge all transcripts into one and split them into sentences
def merge_and_split_transcripts1(transcripts):
    # Iterate through the sorted transcript keys.
    sec = ".!?"
    merged_transcripts = ""
    result = {}
    for chunk_id in transcripts.keys():
        transcript_event = transcripts[chunk_id]
        if not merged_transcripts:
            # If merged_transcripts is empty, start with the first transcript.
            merged_transcripts += transcript_event['transcript'].strip()
        else:
            # Append the transcript to the merged string with a space and lowercase the following first character.
            t = transcript_event['transcript'].strip()
            if len(t) > 1:
                merged_transcripts += " " +  t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        # find first appearance of a sentence-ending character
        while any(char in sec for char in merged_transcripts):
            # split the merged transcript after the first sentence-ending character
            index = next((i for i, char in enumerate(merged_transcripts) if char in sec), None)
            if index is None: break

            # get head with sentence-ending character included
            head = merged_transcripts[:index + 1].strip() # strip removes leading and trailing whitespaces
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head # capitalize the first character
            p = result.get(chunk_id) # get the previous transcript
            if p:
                result[chunk_id] = p + " " + head # append the head to the previous transcript
            else:
                result[chunk_id] = head # set the head as the new transcript
            
            # get tail without sentence-ending character
            merged_transcripts = merged_transcripts[index + 1:].strip()

    # Add the last part of the merged transcript
    chunk_ids = list(transcripts.keys())
    if not chunk_ids: return result
    last_chunk_id = chunk_ids[-1]  # Get the last key

    # Initialize the transcript for the last_key if not present
    if last_chunk_id not in result: result[last_chunk_id] = {}

    # Append the merged transcripts to the result
    if merged_transcripts:
        # Ensure that result[last_key] is a dictionary
        if not isinstance(result.get(last_chunk_id), dict): result[last_chunk_id] = {}
        p = result[last_chunk_id].get('transcript', '')
        result[last_chunk_id]['transcript'] = p + " " + merged_transcripts if p else merged_transcripts

    return result

def translate_with_llm(text, target_language):
    # first try to translate from the cache
    cachekey = target_language + ":" + text
    cached_translation = translation_cache.get(cachekey, '')
    if len(cached_translation) > 0: return cached_translation

    # asl a llm to make the translation
    try:
        openai_endpoint = "https://llm.susi.ai/v1/completions"
        headers = {
            "Content-Type": "application/json",
        }
        answer_object = {
            "translation": "<translated text>",
        }
        prompt = f"Translate this sentence into {target_language}: '{text}'. " + \
                 "The answer must be given as json object in the following format: {json.dumps(answer_object)}"
        data = {
            "model": "text-davinci-003",
            "prompt": prompt,
            "max_tokens": 200,
            "temperature": 0.0,
            "stream": False,
            "messages": [
                #{"role": "system", "content": "Your task is to follow translation instructions. Do only the translation and answer in a short form which shows only the sentence or sentences that had to be translated."},
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(openai_endpoint, headers=headers, json=data)
        response.raise_for_status()
        json_response = response.json()
        #choices = json_response.get('choices', [])
        #if len(choices) > 0:
        #    choice = choices[0]
        #    message = choice.get('message', {})
        #    content = message.get('content', '').strip()
        #    translation_cache[cachekey] = content
        #    return content
        content = json_response.get('content', '').strip()
        if len(content) > 0:
            content = content.strip()
            # parse the json object from the content
            try:
                answer_object = json.loads(content)
                translation = answer_object.get('translation', '')
                translation_cache[cachekey] = translation
                return translation
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing translation response: {str(e)}")
            return text
        return text

    except Exception as e:
        logger.error(f"Error during translation request: {str(e)}")
        return None

def translate(text, source_language, target_language):
    global translation_ongoing
    # first try to translate from the cache
    cachekey = source_language + ":" + target_language + ":" + text
    cached_translation = translation_cache.get(cachekey, '')
    if len(cached_translation) > 0: return cached_translation
    translation_ongoing = True
    try:
        m2m_endpoint = "https://m2m.susi.ai/api/translate.json"
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "src_lang": source_language,
            "out_lang": target_language,
            "text": text,
        }

        response = requests.post(m2m_endpoint, headers=headers, json=data)
        response.raise_for_status()
        json_response = response.json()
        translation_text = json_response.get('translation', '')
        if translation_text:
            translation_cache[cachekey] = translation_text
            translation_ongoing = False
            return translation_text
        else:
            logger.error(f"Error translating text: {text}")
            translation_ongoing = False
            return text

    except Exception as e:
        logger.error(f"Error during translation request: {str(e)}")    
        translation_ongoing = False
        return None