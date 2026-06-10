# transcribe_app/urls.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

from django.urls import path
from . import views
from .views import ServeRootStaticFileView

urlpatterns = [
    path('api/transcripts', views.TranscribeView.as_view(), name='transcripts'),
    path('api/transcripts/count', views.TranscriptsSizeView.as_view(), name='transcripts_count'),
    path('api/transcripts/first', views.GetFirstTranscriptView.as_view(), name='transcripts_first'),
    path('api/transcripts/latest', views.GetLatestTranscriptView.as_view(), name='transcripts_latest'),
    path('api/transcripts/<int:chunk_id>', views.GetTranscriptView.as_view(), name='transcript_by_id'),

    # Deprecated RPC-style aliases (api/ prefixed). Kept for one release so existing clients keep working.
    path('api/transcribe', views.TranscribeView.as_view(legacy=True), name='transcribe'),
    path('api/get_transcript', views.GetTranscriptView.as_view(), name='get_transcript'),
    path('api/get_first_transcript', views.GetFirstTranscriptView.as_view(), name='get_first_transcript'),
    path('api/pop_first_transcript', views.PopFirstTranscriptView.as_view(), name='pop_first_transcript'),
    path('api/get_latest_transcript', views.GetLatestTranscriptView.as_view(), name='get_latest_transcript'),
    path('api/pop_latest_transcript', views.PopLatestTranscriptView.as_view(), name='pop_latest_transcript'),
    path('api/delete_transcript', views.DeleteTranscriptView.as_view(), name='delete_transcript'),
    path('api/list_transcripts', views.ListTranscriptsView.as_view(), name='list_transcripts'),
    path('api/transcripts_size', views.TranscriptsSizeView.as_view(), name='transcripts_size'),

    # Non-prefixed aliases (for Flask HTML clients compatibility).
    path('transcripts', views.TranscribeView.as_view(), name='transcripts_compat'),
    path('transcripts/count', views.TranscriptsSizeView.as_view(), name='transcripts_count_compat'),
    path('transcripts/first', views.GetFirstTranscriptView.as_view(), name='transcripts_first_compat'),
    path('transcripts/latest', views.GetLatestTranscriptView.as_view(), name='transcripts_latest_compat'),
    path('transcripts/<int:chunk_id>', views.GetTranscriptView.as_view(), name='transcript_by_id_compat'),

    path('transcribe', views.TranscribeView.as_view(legacy=True), name='transcribe_compat'),
    path('get_transcript', views.GetTranscriptView.as_view(), name='get_transcript_compat'),
    path('get_first_transcript', views.GetFirstTranscriptView.as_view(), name='get_first_transcript_compat'),
    path('pop_first_transcript', views.PopFirstTranscriptView.as_view(), name='pop_first_transcript_compat'),
    path('get_latest_transcript', views.GetLatestTranscriptView.as_view(), name='get_latest_transcript_compat'),
    path('pop_latest_transcript', views.PopLatestTranscriptView.as_view(), name='pop_latest_transcript_compat'),
    path('delete_transcript', views.DeleteTranscriptView.as_view(), name='delete_transcript_compat'),
    path('list_transcripts', views.ListTranscriptsView.as_view(), name='list_transcripts_compat'),
    path('transcripts_size', views.TranscriptsSizeView.as_view(), name='transcripts_size_compat'),

    path('', ServeRootStaticFileView.as_view(), name='root_view'),
    path('<path:file_name>', views.ServeRootStaticFileView.as_view(), name='serve_root_static_file'),
]
