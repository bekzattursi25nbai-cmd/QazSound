from django.urls import path

from . import views

app_name = "tracks"

urlpatterns = [
    path("", views.home, name="home"),
    path("tracks/", views.track_list, name="track_list"),
    path("tracks/add/", views.track_create, name="track_create"),
    path("tracks/youtube/metadata/", views.youtube_metadata_preview, name="youtube_metadata_preview"),
    path("tracks/<int:track_id>/stream/", views.youtube_audio_stream, name="youtube_audio_stream"),
    path("tracks/<int:track_id>/", views.track_detail, name="track_detail"),
    path("tracks/<int:track_id>/edit/", views.track_edit, name="track_edit"),
    path("tracks/<int:track_id>/delete/", views.track_delete, name="track_delete"),
]
