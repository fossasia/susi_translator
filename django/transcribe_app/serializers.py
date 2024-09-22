# transcribe_app/serializers.py
from rest_framework import serializers

class TranscribeInputSerializer(serializers.Serializer):
    audio_b64 = serializers.CharField(required=True, help_text='Base64 encoded audio data')
    chunk_id = serializers.CharField(required=True, help_text='ID of the audio chunk')
    tenant_id = serializers.CharField(required=False, default='0000', help_text='Tenant ID')
    translate_from = serializers.CharField(required=False, default='translate_from', help_text='Source Language')
    translate_to = serializers.CharField(required=False, default='translate_to', help_text='Target Language')

class TranscribeResponseSerializer(serializers.Serializer):
    chunk_id = serializers.CharField(help_text='ID of the audio chunk')
    tenant_id = serializers.CharField(help_text='Tenant ID')
    status = serializers.CharField(help_text='Processing flag')

class TranscriptResponseSerializer(serializers.Serializer):
    chunk_id = serializers.CharField(help_text='ID of the audio chunk')
    transcript = serializers.CharField(help_text='The transcribed text')

class ListTranscriptsResponseSerializer(serializers.Serializer):
    transcripts = TranscriptResponseSerializer(many=True)

class SizeResponseSerializer(serializers.Serializer):
    size = serializers.IntegerField(help_text='The number of transcripts')
