from typing import TYPE_CHECKING

from django.conf import settings

from .downloader import (
    YouTubeExtractionDependencyError,
    YouTubeExtractionError,
    extract_bestaudio_stream,
    extract_youtube_metadata,
)
from .models import Artist, Track
from .utils import extract_youtube_id, is_youtube_domain, normalize_youtube_url

if TYPE_CHECKING:
    from .forms import TrackForm


class TrackProcessingError(Exception):
    """Raised when track business logic fails during create/update."""


def is_valid_youtube_url(url: str) -> bool:
    return is_youtube_domain(url) and extract_youtube_id(url) is not None


def build_youtube_embed_url(video_id: str) -> str:
    if not video_id:
        return ""
    return f"https://www.youtube.com/embed/{video_id}"


def fetch_youtube_metadata(youtube_url: str) -> dict:
    normalized_url = normalize_youtube_url(youtube_url)
    video_id = extract_youtube_id(normalized_url)
    if not video_id:
        return {}

    try:
        metadata = extract_youtube_metadata(
            normalized_url,
            request_timeout=getattr(settings, "YTDLP_REQUEST_TIMEOUT_SECONDS", 12),
        )
    except (YouTubeExtractionDependencyError, YouTubeExtractionError):
        return {}

    if not metadata:
        return {}

    metadata["video_id"] = video_id
    metadata["normalized_url"] = normalized_url
    metadata["embed_url"] = build_youtube_embed_url(video_id)
    return metadata


def fetch_youtube_stream(youtube_url: str) -> dict:
    normalized_url = normalize_youtube_url(youtube_url)
    video_id = extract_youtube_id(normalized_url)
    if not video_id:
        return {}

    if not getattr(settings, "ENABLE_YTDLP_YOUTUBE_STREAM", True):
        return {}

    format_selector = getattr(settings, "YTDLP_STREAM_FORMAT", "bestaudio/best")
    try:
        stream = extract_bestaudio_stream(
            normalized_url,
            format_selector=format_selector,
            request_timeout=getattr(settings, "YTDLP_REQUEST_TIMEOUT_SECONDS", 12),
        )
    except (YouTubeExtractionDependencyError, YouTubeExtractionError):
        return {}

    if not stream:
        return {}

    stream["video_id"] = video_id
    stream["normalized_url"] = normalized_url
    stream["embed_url"] = build_youtube_embed_url(video_id)
    return stream


def _resolve_artist(artist_name: str) -> Artist:
    cleaned = (artist_name or "").strip()
    artist = Artist.objects.filter(name__iexact=cleaned).first()
    if artist:
        return artist
    return Artist.objects.create(name=cleaned)


def _apply_track_source_logic(track: Track, form: "TrackForm") -> Track:
    track.artist = _resolve_artist(form.cleaned_data["artist_name"])

    if track.source_type == Track.SourceType.YOUTUBE:
        normalized_url = normalize_youtube_url(form.cleaned_data.get("youtube_url", ""))
        if not normalized_url:
            raise TrackProcessingError("YouTube URL is required for streaming.")

        track.youtube_url = normalized_url or None
        track.youtube_id = form.youtube_id or extract_youtube_id(normalized_url)
        track.audio_file = None

        metadata = form.youtube_metadata or fetch_youtube_metadata(normalized_url)

        if not track.title:
            track.title = (metadata.get("title") or "").strip()

        if not track.external_cover_url:
            track.external_cover_url = (metadata.get("thumbnail_url") or "").strip()
        if not track.duration_seconds and metadata.get("duration_seconds"):
            track.duration_seconds = metadata["duration_seconds"]
    else:
        track.youtube_url = None
        track.youtube_id = None
        track.external_cover_url = ""

    return track


def create_track(owner, form: "TrackForm") -> Track:
    track = form.save(commit=False)
    track.owner = owner
    track = _apply_track_source_logic(track, form)
    track.save()
    form.save_m2m()
    return track


def update_track(track: Track, form: "TrackForm") -> Track:
    updated_track = form.save(commit=False)
    updated_track.owner = track.owner
    updated_track = _apply_track_source_logic(updated_track, form)
    updated_track.save()
    form.save_m2m()
    return updated_track


def delete_track(track: Track) -> None:
    track.delete()
