from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from .models import Track
from .services import fetch_youtube_metadata, is_valid_youtube_url
from .utils import extract_youtube_id, normalize_youtube_url


ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg"}
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "application/ogg",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_AUDIO_SIZE = 30 * 1024 * 1024
MAX_IMAGE_SIZE = 5 * 1024 * 1024


class TrackForm(forms.ModelForm):
    artist_name = forms.CharField(
        max_length=120,
        required=False,
        label="Artist",
        widget=forms.TextInput(attrs={"placeholder": "Type artist or channel name"}),
    )

    class Meta:
        model = Track
        fields = [
            "source_type",
            "title",
            "description",
            "artist_name",
            "genres",
            "cover",
            "external_cover_url",
            "audio_file",
            "youtube_url",
            "duration_seconds",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "genres": forms.SelectMultiple(attrs={"size": 6}),
            "source_type": forms.Select(),
            "youtube_url": forms.URLInput(attrs={"placeholder": "https://www.youtube.com/watch?v=..."}),
            "external_cover_url": forms.URLInput(attrs={"placeholder": "Thumbnail URL (optional)"}),
        }

    youtube_metadata: dict

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.youtube_metadata = {}
        self.youtube_id = None

        if self.instance and self.instance.pk and self.instance.artist_id:
            self.fields["artist_name"].initial = self.instance.artist.name

        self.fields["title"].required = False
        self.fields["audio_file"].required = False
        self.fields["youtube_url"].required = False
        self.fields["external_cover_url"].required = False

        for field in self.fields.values():
            css_class = "form-input"
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {css_class}".strip()

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean_artist_name(self):
        return (self.cleaned_data.get("artist_name") or "").strip()

    def clean_youtube_url(self):
        youtube_url = (self.cleaned_data.get("youtube_url") or "").strip()
        if not youtube_url:
            self.youtube_id = None
            return None

        if not is_valid_youtube_url(youtube_url):
            raise ValidationError("Only youtube.com or youtu.be links are allowed.")

        youtube_id = extract_youtube_id(youtube_url)
        if not youtube_id:
            raise ValidationError("Invalid YouTube link.")

        self.youtube_id = youtube_id
        return normalize_youtube_url(youtube_url)

    def clean_audio_file(self):
        audio = self.cleaned_data.get("audio_file")
        if not audio:
            return audio

        ext = Path(audio.name).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValidationError("Only MP3, WAV, and OGG files are allowed.")

        content_type = getattr(audio, "content_type", "")
        if content_type and content_type.lower() not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise ValidationError("Uploaded file does not look like a valid audio format.")

        if audio.size > MAX_AUDIO_SIZE:
            raise ValidationError("Audio file must be 30MB or smaller.")
        return audio

    def clean_cover(self):
        cover = self.cleaned_data.get("cover")
        if not cover:
            return cover

        ext = Path(cover.name).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValidationError("Cover must be JPG, PNG, WEBP, or GIF.")

        content_type = getattr(cover, "content_type", "")
        if content_type and not content_type.lower().startswith("image/"):
            raise ValidationError("Uploaded cover does not look like an image.")

        if cover.size > MAX_IMAGE_SIZE:
            raise ValidationError("Cover image must be 5MB or smaller.")
        return cover

    def clean(self):
        cleaned_data = super().clean()

        source_type = cleaned_data.get("source_type")
        audio_file = cleaned_data.get("audio_file")
        youtube_url = cleaned_data.get("youtube_url") or ""
        title = cleaned_data.get("title", "").strip()
        artist_name = cleaned_data.get("artist_name", "").strip()
        external_cover_url = cleaned_data.get("external_cover_url", "").strip()

        existing_audio = bool(self.instance and self.instance.pk and self.instance.audio_file)

        if source_type == Track.SourceType.UPLOAD:
            if not audio_file and not existing_audio:
                self.add_error("audio_file", "Audio file is required for upload source.")

            if not title:
                self.add_error("title", "Title is required.")
            if not artist_name:
                self.add_error("artist_name", "Artist name is required.")

            cleaned_data["youtube_url"] = None
            self.youtube_id = None
            cleaned_data["external_cover_url"] = ""

        elif source_type == Track.SourceType.YOUTUBE:
            if not youtube_url:
                self.add_error("youtube_url", "YouTube URL is required for YouTube source.")
            else:
                youtube_id = self.youtube_id or extract_youtube_id(youtube_url)
                if not youtube_id:
                    self.add_error("youtube_url", "Invalid YouTube link.")
                else:
                    self.youtube_id = youtube_id

                metadata = fetch_youtube_metadata(youtube_url)
                self.youtube_metadata = metadata

                if not title and metadata.get("title"):
                    title = metadata["title"].strip()
                    cleaned_data["title"] = title

                if not artist_name and metadata.get("author_name"):
                    artist_name = metadata["author_name"].strip()
                    cleaned_data["artist_name"] = artist_name

                if not external_cover_url and metadata.get("thumbnail_url"):
                    cleaned_data["external_cover_url"] = metadata["thumbnail_url"].strip()

                if not cleaned_data.get("duration_seconds") and metadata.get("duration_seconds"):
                    cleaned_data["duration_seconds"] = metadata["duration_seconds"]

            if not cleaned_data.get("title", "").strip():
                self.add_error("title", "Title is required (or use Fetch metadata).")

            if not cleaned_data.get("artist_name", "").strip():
                self.add_error("artist_name", "Artist name is required (or use Fetch metadata).")

        else:
            self.add_error("source_type", "Unsupported source type.")

        return cleaned_data
