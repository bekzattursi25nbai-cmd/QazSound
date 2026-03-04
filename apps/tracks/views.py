from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.interactions.selectors import get_liked_track_ids

from .forms import TrackForm
from .models import Track
from .selectors import (
    get_all_genres,
    get_fresh_tracks,
    get_track_by_id,
    get_track_list,
    get_trending_tracks,
)
from .services import (
    TrackProcessingError,
    create_track,
    delete_track,
    fetch_youtube_stream,
    fetch_youtube_metadata,
    is_valid_youtube_url,
    update_track,
)


def _collect_liked_track_ids(request, tracks: list[Track] | tuple[Track, ...]) -> set[int]:
    if not request.user.is_authenticated:
        return set()
    ids = [track.id for track in tracks]
    return get_liked_track_ids(request.user, track_ids=ids)


def home(request):
    search = request.GET.get("q", "").strip()
    genre = request.GET.get("genre", "").strip()

    featured_tracks = list(get_track_list(search=search or None, genre=genre or None)[:12])
    fresh_tracks = list(get_fresh_tracks(limit=8, search=search or None, genre=genre or None))
    trending_tracks = list(get_trending_tracks(limit=8, search=search or None, genre=genre or None))
    genres = get_all_genres()

    liked_track_ids = _collect_liked_track_ids(
        request,
        tracks=[*featured_tracks, *fresh_tracks, *trending_tracks],
    )

    return render(
        request,
        "tracks/home.html",
        {
            "featured_tracks": featured_tracks,
            "fresh_tracks": fresh_tracks,
            "trending_tracks": trending_tracks,
            "genres": genres,
            "search": search,
            "active_genre": genre,
            "liked_track_ids": liked_track_ids,
        },
    )


def track_list(request):
    search = request.GET.get("q", "").strip()
    genre = request.GET.get("genre", "").strip()

    tracks = list(get_track_list(search=search or None, genre=genre or None))
    genres = get_all_genres()
    liked_track_ids = _collect_liked_track_ids(request, tracks=tracks)

    return render(
        request,
        "tracks/track_list.html",
        {
            "tracks": tracks,
            "genres": genres,
            "search": search,
            "active_genre": genre,
            "liked_track_ids": liked_track_ids,
        },
    )


def track_detail(request, track_id: int):
    try:
        track = get_track_by_id(track_id)
    except Track.DoesNotExist as exc:
        raise Http404("Track not found") from exc

    liked_track_ids = _collect_liked_track_ids(request, tracks=[track])
    return render(
        request,
        "tracks/track_detail.html",
        {
            "track": track,
            "is_liked": track.id in liked_track_ids,
        },
    )


def _ensure_owner(request, track: Track):
    if track.owner_id != request.user.id:
        messages.error(request, "You do not have permission to modify this track.")
        return False
    return True


@login_required
def track_create(request):
    if request.method == "POST":
        form = TrackForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                track = create_track(request.user, form)
            except TrackProcessingError as exc:
                form.add_error(None, str(exc))
                messages.error(request, str(exc))
            else:
                messages.success(request, "Track published successfully.")
                return redirect("tracks:track_detail", track_id=track.id)
        else:
            messages.error(request, "Please correct the errors and try again.")
    else:
        form = TrackForm()

    return render(request, "tracks/track_form.html", {"form": form, "is_create": True})


@login_required
def track_edit(request, track_id: int):
    try:
        track = get_track_by_id(track_id)
    except Track.DoesNotExist as exc:
        raise Http404("Track not found") from exc

    if not _ensure_owner(request, track):
        return redirect("tracks:track_detail", track_id=track.id)

    if request.method == "POST":
        form = TrackForm(request.POST, request.FILES, instance=track)
        if form.is_valid():
            try:
                track = update_track(track, form)
            except TrackProcessingError as exc:
                form.add_error(None, str(exc))
                messages.error(request, str(exc))
            else:
                messages.success(request, "Track updated successfully.")
                return redirect("tracks:track_detail", track_id=track.id)
        else:
            messages.error(request, "Please correct the errors and try again.")
    else:
        form = TrackForm(instance=track)

    return render(request, "tracks/track_form.html", {"form": form, "track": track, "is_create": False})


@login_required
def track_delete(request, track_id: int):
    try:
        track = get_track_by_id(track_id)
    except Track.DoesNotExist as exc:
        raise Http404("Track not found") from exc

    if not _ensure_owner(request, track):
        return redirect("tracks:track_detail", track_id=track.id)

    if request.method == "POST":
        delete_track(track)
        messages.success(request, "Track deleted.")
        return redirect("tracks:home")

    return render(request, "tracks/track_confirm_delete.html", {"track": track})


@login_required
def youtube_metadata_preview(request):
    youtube_url = request.GET.get("url", "").strip()
    if not youtube_url:
        return JsonResponse({"detail": "YouTube URL is required."}, status=400)

    if not is_valid_youtube_url(youtube_url):
        return JsonResponse({"detail": "Invalid YouTube URL."}, status=400)

    metadata = fetch_youtube_metadata(youtube_url)
    if not metadata:
        return JsonResponse({"detail": "Could not fetch metadata for this video."}, status=404)

    return JsonResponse(
        {
            "title": metadata.get("title", ""),
            "author_name": metadata.get("author_name", ""),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "duration_seconds": metadata.get("duration_seconds"),
            "normalized_url": metadata.get("normalized_url", youtube_url),
            "embed_url": metadata.get("embed_url", ""),
        }
    )


@require_GET
def youtube_audio_stream(request, track_id: int):
    try:
        track = get_track_by_id(track_id)
    except Track.DoesNotExist as exc:
        raise Http404("Track not found") from exc

    if track.source_type != Track.SourceType.YOUTUBE or not track.youtube_url:
        return JsonResponse({"detail": "This track does not have a YouTube source."}, status=400)

    stream_data = fetch_youtube_stream(track.youtube_url)
    stream_url = (stream_data.get("audio_url") or "").strip()
    if not stream_url:
        return JsonResponse({"detail": "Could not resolve YouTube audio stream URL."}, status=502)

    wants_json = request.GET.get("json") == "1" or "application/json" in request.headers.get("Accept", "")
    if wants_json:
        return JsonResponse(
            {
                "audio_url": stream_url,
                "format_id": stream_data.get("format_id", ""),
                "ext": stream_data.get("ext", ""),
                "acodec": stream_data.get("acodec", ""),
                "title": stream_data.get("title", ""),
                "duration_seconds": stream_data.get("duration_seconds"),
                "thumbnail_url": stream_data.get("thumbnail_url", ""),
            }
        )

    return redirect(stream_url)
