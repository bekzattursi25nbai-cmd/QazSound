from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.urls import reverse
from django.template.defaultfilters import slugify

from .utils import extract_youtube_id


class Artist(models.Model):
    name = models.CharField(max_length=120)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="covers/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Genre(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Track(models.Model):
    class SourceType(models.TextChoices):
        UPLOAD = "UPLOAD", "Upload"
        YOUTUBE = "YOUTUBE", "YouTube"

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    cover = models.ImageField(upload_to="covers/", blank=True, null=True)
    external_cover_url = models.URLField(blank=True)
    audio_file = models.FileField(upload_to="audio/", blank=True, null=True)
    source_type = models.CharField(max_length=12, choices=SourceType.choices, default=SourceType.UPLOAD)
    youtube_url = models.URLField(blank=True, null=True)
    youtube_id = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    is_featured = models.BooleanField(default=False)
    duration_seconds = models.PositiveIntegerField(blank=True, null=True)
    plays_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="tracks")
    genres = models.ManyToManyField(Genre, related_name="tracks", blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracks",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} - {self.artist.name}"

    @property
    def likes_count(self) -> int:
        annotated_value = getattr(self, "likes_total", None)
        if annotated_value is not None:
            return int(annotated_value)
        return self.likes.count()

    def is_youtube(self) -> bool:
        return self.source_type == self.SourceType.YOUTUBE

    @property
    def cover_url(self) -> str:
        if self.cover:
            return self.cover.url

        if self.external_cover_url:
            validator = URLValidator()
            try:
                validator(self.external_cover_url)
                return self.external_cover_url
            except Exception:
                pass

        return f"{settings.STATIC_URL}img/placeholders/cover.jpg"

    @property
    def audio_url(self) -> str:
        if self.audio_file:
            return self.audio_file.url
        if self.is_youtube() and self.pk and (self.youtube_url or self.youtube_id):
            return reverse("tracks:youtube_audio_stream", args=[self.pk])
        return ""

    def embed_url(self) -> str:
        if self.youtube_id:
            return f"https://www.youtube.com/embed/{self.youtube_id}"

        # Safety net for older rows without youtube_id populated yet.
        fallback_video_id = extract_youtube_id(self.youtube_url or "")
        if fallback_video_id:
            return f"https://www.youtube.com/embed/{fallback_video_id}"
        return ""

    @property
    def youtube_embed_url(self) -> str:
        return self.embed_url()
