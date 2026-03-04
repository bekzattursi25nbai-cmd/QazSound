from __future__ import annotations

import importlib
import math
from typing import Any


class YouTubeExtractionError(Exception):
    """Raised when yt-dlp cannot read YouTube metadata/stream information."""


class YouTubeExtractionDependencyError(YouTubeExtractionError):
    """Raised when yt-dlp is not available in the runtime."""


def _resolve_yt_dlp() -> tuple[Any, type[Exception]]:
    try:
        module = importlib.import_module("yt_dlp")
        utils = importlib.import_module("yt_dlp.utils")
        return module.YoutubeDL, utils.DownloadError
    except Exception as exc:  # pragma: no cover - env dependent
        raise YouTubeExtractionDependencyError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        ) from exc


def _base_ydl_options(*, format_selector: str | None = None, request_timeout: int = 12) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": request_timeout,
        "cachedir": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android"],
                "skip": ["dash", "hls"],
            }
        },
    }
    if format_selector:
        options["format"] = format_selector
    return options


def _first_playlist_entry(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("_type") != "playlist":
        return info
    for entry in info.get("entries") or []:
        if isinstance(entry, dict) and entry:
            return entry
    raise YouTubeExtractionError("Playlist URL did not contain a playable entry.")


def _pick_thumbnail_url(info: dict[str, Any]) -> str:
    direct = str(info.get("thumbnail") or "").strip()
    if direct:
        return direct

    thumbnails = info.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("url") or "").strip()
            if candidate:
                return candidate
    return ""


def _audio_quality_score(format_payload: dict[str, Any]) -> tuple[float, float, float]:
    abr = format_payload.get("abr")
    asr = format_payload.get("asr")
    tbr = format_payload.get("tbr")

    abr_score = float(abr) if isinstance(abr, (int, float)) and math.isfinite(float(abr)) else 0.0
    asr_score = float(asr) if isinstance(asr, (int, float)) and math.isfinite(float(asr)) else 0.0
    tbr_score = float(tbr) if isinstance(tbr, (int, float)) and math.isfinite(float(tbr)) else 0.0
    return abr_score, asr_score, tbr_score


def _pick_best_audio_format(info: dict[str, Any]) -> dict[str, Any]:
    direct_url = str(info.get("url") or "").strip()
    if direct_url:
        return info

    formats = info.get("formats") or []
    candidates = []
    for item in formats:
        if not isinstance(item, dict):
            continue
        if not str(item.get("url") or "").strip():
            continue
        if str(item.get("acodec") or "none") == "none":
            continue
        candidates.append(item)

    if not candidates:
        raise YouTubeExtractionError("Could not resolve an audio stream URL.")

    candidates.sort(key=_audio_quality_score, reverse=True)
    return candidates[0]


def _extract_info(url: str, *, format_selector: str | None = None, request_timeout: int = 12) -> dict[str, Any]:
    YoutubeDL, DownloadError = _resolve_yt_dlp()

    try:
        with YoutubeDL(_base_ydl_options(format_selector=format_selector, request_timeout=request_timeout)) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise YouTubeExtractionError(f"Could not read YouTube metadata: {exc}") from exc

    if not isinstance(info, dict):
        raise YouTubeExtractionError("Unexpected metadata format returned by yt-dlp.")

    return _first_playlist_entry(info)


def extract_youtube_metadata(youtube_url: str, *, request_timeout: int = 12) -> dict[str, Any]:
    info = _extract_info(youtube_url, request_timeout=request_timeout)
    return {
        "title": str(info.get("title") or "").strip(),
        "author_name": str(info.get("uploader") or info.get("channel") or "").strip(),
        "thumbnail_url": _pick_thumbnail_url(info),
        "duration_seconds": int(info.get("duration")) if isinstance(info.get("duration"), (int, float)) else None,
        "video_id": str(info.get("id") or "").strip(),
        "webpage_url": str(info.get("webpage_url") or "").strip(),
    }


def extract_bestaudio_stream(
    youtube_url: str,
    *,
    format_selector: str = "bestaudio/best",
    request_timeout: int = 12,
) -> dict[str, Any]:
    info = _extract_info(
        youtube_url,
        format_selector=format_selector,
        request_timeout=request_timeout,
    )
    selected_format = _pick_best_audio_format(info)
    stream_url = str(selected_format.get("url") or "").strip()
    if not stream_url:
        raise YouTubeExtractionError("yt-dlp did not return a stream URL.")

    return {
        "audio_url": stream_url,
        "format_id": str(selected_format.get("format_id") or "").strip(),
        "ext": str(selected_format.get("ext") or "").strip(),
        "acodec": str(selected_format.get("acodec") or "").strip(),
        "title": str(info.get("title") or "").strip(),
        "author_name": str(info.get("uploader") or info.get("channel") or "").strip(),
        "thumbnail_url": _pick_thumbnail_url(info),
        "duration_seconds": int(info.get("duration")) if isinstance(info.get("duration"), (int, float)) else None,
        "video_id": str(info.get("id") or "").strip(),
        "webpage_url": str(info.get("webpage_url") or "").strip(),
    }
