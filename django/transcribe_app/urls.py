# transcribe_app/urls.py
# (C) Michael Peter Christen 2024
# Licensed under Apache License Version 2.0

from django.urls import path
from . import views
from .views import ServeRootStaticFileView

urlpatterns = [
    path('api/transcribe', views.TranscribeView.as_view(), name='transcribe'),
    path('api/get_transcript', views.GetTranscriptView.as_view(), name='get_transcript'),
    path('api/get_first_transcript', views.GetFirstTranscriptView.as_view(), name='get_first_transcript'),
    path('api/pop_first_transcript', views.PopFirstTranscriptView.as_view(), name='pop_first_transcript'),
    path('api/get_latest_transcript', views.GetLatestTranscriptView.as_view(), name='get_latest_transcript'),
    path('api/pop_latest_transcript', views.PopLatestTranscriptView.as_view(), name='pop_latest_transcript'),
    path('api/delete_transcript', views.DeleteTranscriptView.as_view(), name='delete_transcript'),
    path('api/list_transcripts', views.ListTranscriptsView.as_view(), name='list_transcripts'),
    path('api/transcripts_size', views.TranscriptsSizeView.as_view(), name='transcripts_size'),
    path('', ServeRootStaticFileView.as_view(), name='root_view'),
    path('<path:file_name>', views.ServeRootStaticFileView.as_view(), name='serve_root_static_file'),
]