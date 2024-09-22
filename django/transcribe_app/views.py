# transcribe_app/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import JSONParser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .transcribe_utils import transcriptd, audio_stack, process_audio, merge_and_split_transcripts, translate, logger
from .serializers import (
    TranscribeInputSerializer,
    TranscribeResponseSerializer,
    TranscriptResponseSerializer,
    ListTranscriptsResponseSerializer,
    SizeResponseSerializer
)
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from django.http import HttpResponse, Http404
from scipy.io.wavfile import write as wav_write
import numpy as np
import mimetypes
import threading
import pybars
import time
import os

# Start the audio processing thread
threading.Thread(target=process_audio).start()

def home(request):
    return HttpResponse("Welcome to the Transcription API!")

@method_decorator(csrf_exempt, name='dispatch')
class TranscribeView(APIView):
    parser_classes = [JSONParser]

    @swagger_auto_schema(
        request_body=TranscribeInputSerializer,
        responses={200: TranscribeResponseSerializer}
    )
    def post(self, request):
        """
        The /transcribe endpoint expects JSON objects with base64-encoded audio binaries.
        Each chunk should have a unique chunk_id.
        The server processes each chunk and transcribes the audio using Whisper.
        """
        serializer = TranscribeInputSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            tenant_id = data.get('tenant_id', '0000')
            translate_from = data.get('translate_from', None)
            translate_to = data.get('translate_to', None)
            audio_b64 = data['audio_b64']
            chunk_id = data['chunk_id']
            audio_stack.put((tenant_id, chunk_id, audio_b64, translate_from, translate_to))
            #print("queue length: " + str(audio_stack.qsize()))
            logger.debug(f"Received chunk {chunk_id} with tenant_id {tenant_id}")
            response_data = {'chunk_id': chunk_id, 'tenant_id': tenant_id, 'status': 'processing'}
            #print("received chunk " + chunk_id + " with " + str(len(audio_b64)) + " bytes")
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            logger.error("Invalid data in TranscribeView")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class GetTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('chunk_id', openapi.IN_QUERY, description="Chunk ID", type=openapi.TYPE_STRING),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Retrieve the transcript for a given chunk_id.
        If the chunk_id is not found, an empty transcript is returned.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return Response({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.GET.get('sentences', 'false') == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            chunk_id = request.GET.get('chunk_id')
            if chunk_id in t:
                transcript = t.get(chunk_id, {}).get('transcript', '')
                return Response({'chunk_id': chunk_id, 'transcript': transcript})
            else:
                return Response({'chunk_id': chunk_id, 'transcript': ''})

@method_decorator(csrf_exempt, name='dispatch')
class GetFirstTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('from', openapi.IN_QUERY, description="Starting chunk ID", type=openapi.TYPE_STRING, default='0'),
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Retrieve the first transcript for a given tenant_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return Response({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.GET.get('sentences', 'false') == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            fromid = request.GET.get('from', '0')
            sorted_keys = sorted(t.keys())
            first_chunk_id = next((k for k in sorted_keys if int(k) >= int(fromid)), None)
            first_transcript = t[first_chunk_id]['transcript']
            return Response({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@method_decorator(csrf_exempt, name='dispatch')
class PopFirstTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('from', openapi.IN_QUERY, description="Starting chunk ID", type=openapi.TYPE_STRING, default='0'),
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Retrieve and remove the first transcript for a given tenant_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        if len(t) == 0:
            return Response({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.GET.get('sentences', 'false') == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            fromid = request.GET.get('from', '0')
            sorted_keys = sorted(t.keys())
            first_chunk_id = next((k for k in sorted_keys if int(k) >= int(fromid)), None)
            first_transcript = t.pop(first_chunk_id, {}).get('transcript', '')
            return Response({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@method_decorator(csrf_exempt, name='dispatch')
class GetLatestTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('until', openapi.IN_QUERY, description="End chunk ID", type=openapi.TYPE_STRING, default=str(int(time.time() * 1000)))
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Retrieve the latest transcript for a given tenant_id. Optionally translate it into another language.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        transcripts = transcriptd.get(tenant_id, {})
        
        if len(transcripts) == 0:
            return Response({})
        else:
            untilid = request.GET.get('until', str(int(time.time() * 1000)))
            sorted_keys = sorted(transcripts.keys(), reverse=True)
            # remove all keys that are greater than untilid
            sorted_keys = [k for k in sorted_keys if int(k) <= int(untilid)]
            # now extract the first three keys from largest to smallest
            extracted_keys = sorted_keys[:4] if len(sorted_keys) > 3 else sorted_keys
            # from the transcripts dictionary, extract the transcripts for the extracted keys
            extracted_transcripts = {k: transcripts[k] for k in extracted_keys}
            # now sort the extracted transcripts by key again, now lowest to highest
            extracted_transcripts = {k: v for k, v in sorted(extracted_transcripts.items())}    
            return Response(extracted_transcripts)
            
@method_decorator(csrf_exempt, name='dispatch')
class PopLatestTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('until', openapi.IN_QUERY, description="End chunk ID", type=openapi.TYPE_STRING, default=str(int(time.time() * 1000))),
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Retrieve and remove the latest transcript for a given tenant_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        untilid = request.GET.get('until', str(int(time.time() * 1000)))
        sentences = request.GET.get('sentences', 'false') == 'true'
        t = transcriptd.get(tenant_id, {})
        if sentences: t = merge_and_split_transcripts(t)
        sorted_keys = sorted(t.keys(), reverse=True)
        latest_chunk_id = next((k for k in sorted_keys if int(k) < int(untilid)), None)
        if latest_chunk_id in t:
            latest_transcript = t.pop(latest_chunk_id, {}).get('transcript', '')
            return Response({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})
        else:
            return Response({'chunk_id': '-1', 'transcript': ''})

@method_decorator(csrf_exempt, name='dispatch')
class DeleteTranscriptView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('chunk_id', openapi.IN_QUERY, description="Chunk ID", type=openapi.TYPE_STRING),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
        ],
        responses={200: TranscriptResponseSerializer}
    )
    def get(self, request):
        """
        Delete a transcript for a given tenant_id and chunk_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        chunk_id = request.GET.get('chunk_id')
        sentences = request.GET.get('sentences', 'false') == 'true'
        t = transcriptd.get(tenant_id, {})
        if sentences: t = merge_and_split_transcripts(t)
        if chunk_id in t:
            entry = t.pop(chunk_id)
            return Response({'chunk_id': chunk_id, 'transcript': entry['transcript']})
        else:
            return Response({'chunk_id': chunk_id, 'transcript': ''})

@method_decorator(csrf_exempt, name='dispatch')
class ListTranscriptsView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('from', openapi.IN_QUERY, description="Starting chunk ID", type=openapi.TYPE_STRING, default='0'),
            openapi.Parameter('until', openapi.IN_QUERY, description="End chunk ID", type=openapi.TYPE_STRING, default=str(int(time.time() * 1000))),
        ],
        responses={200: ListTranscriptsResponseSerializer}
    )
    def get(self, request):
        """
        List all transcripts for a given tenant_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        fromid = request.GET.get('from', '0')
        untilid = request.GET.get('until', str(int(time.time() * 1000)))
        sentences = request.GET.get('sentences', 'false') == 'true'
        t = transcriptd.get(tenant_id, {})
        if sentences: t = merge_and_split_transcripts(t)
        transcripts = {k: v for k, v in t.items() if int(fromid) <= int(k) <= int(untilid)}
        return Response({'transcripts': [{'chunk_id': k, 'transcript': v['transcript']} for k, v in transcripts.items()]})

@method_decorator(csrf_exempt, name='dispatch')
class TranscriptsSizeView(APIView):
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('tenant_id', openapi.IN_QUERY, description="Tenant ID", type=openapi.TYPE_STRING, default='0000'),
            openapi.Parameter('sentences', openapi.IN_QUERY, description="Merge and split transcripts into sentences", type=openapi.TYPE_BOOLEAN, default=False),
            openapi.Parameter('from', openapi.IN_QUERY, description="Starting chunk ID", type=openapi.TYPE_STRING, default='0'),
            openapi.Parameter('until', openapi.IN_QUERY, description="End chunk ID", type=openapi.TYPE_STRING, default=str(int(time.time() * 1000))),
        ],
        responses={200: SizeResponseSerializer}
    )
    def get(self, request):
        """
        Get the size of the transcripts for a given tenant_id.
        """
        tenant_id = request.GET.get('tenant_id', '0000')
        t = transcriptd.get(tenant_id, {})
        sentences = request.GET.get('sentences', 'false') == 'true'
        if sentences: t = merge_and_split_transcripts(t)
        fromid = request.GET.get('from', '0')
        untilid = request.GET.get('until', str(int(time.time() * 1000)))
        transcripts = {k: v for k, v in t.items() if k.isdigit() and int(fromid) <= int(k) <= int(untilid)}
        return Response({'size': len(transcripts)})

@method_decorator(csrf_exempt, name='dispatch')
class ServeRootStaticFileView(APIView):
    """
    Serve static files directly from the root path via an API endpoint.
    Optionally apply Handlebars.js-like transformations using PyBars.
    """

    def get(self, request, file_name):
        # Path to the static file
        file_path = os.path.join(settings.STATIC_FILES, file_name)

        # Check if the file exists
        if not os.path.exists(file_path):
            raise Http404(f"File '{file_name}' not found.")

        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()

        # Get the content type based on the file extension
        guessed_type, _ = mimetypes.guess_type(file_path)
        
        # Check if transformation is requested via query param (e.g., /index.html/?transform=true)
        if request.GET.get('transform', 'false').lower() == 'true':
            # Apply Handlebars-like transformation
            context = {
                "title": "Dynamic Page",
                "content": "This content was dynamically injected.",
            }

            compiler = pybars.Compiler()
            template = compiler.compile(file_content)
            transformed_content = template(context)

            # Return transformed content as HTML
            return HttpResponse(transformed_content, content_type='text/html')

        # Serve the static file as-is
        return HttpResponse(file_content, content_type=guessed_type or 'application/octet-stream')
