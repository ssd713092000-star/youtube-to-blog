"""YouTube metadata + transcripts.

YouTube blocks most cloud-provider IPs, so production traffic goes through a residential proxy
(Webshare credentials in Secret Manager, or any HTTP proxy URL). Results are cached in the content
bucket under cache/videos/{id}/ so the preview, ingest and retries hit YouTube at most once."""

import asyncio
import json
import logging
import re
import time
from typing import Any, Literal, Protocol, TypedDict

from app.core.errors import TransientFetchError
from app.services.blobs import BlobStore

log = logging.getLogger(__name__)

_ID = r"([A-Za-z0-9_-]{11})"
_PATTERNS = [
    re.compile(rf"(?:youtube\.com|youtube-nocookie\.com)/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/){_ID}"),
    re.compile(rf"youtu\.be/{_ID}"),
    re.compile(rf"^{_ID}$"),
]
METADATA_TTL_SECONDS = 24 * 3600


def parse_video_id(url_or_id: str) -> str | None:
    s = url_or_id.strip()
    for p in _PATTERNS:
        if m := p.search(s):
            return m.group(1)
    return None


class Chapter(TypedDict):
    title: str
    start: float
    end: float


class VideoMetadata(TypedDict):
    video_id: str
    title: str
    description: str
    channel: str
    duration: int
    chapters: list[Chapter]
    thumbnail_url: str


class Snippet(TypedDict):
    text: str
    start: float
    duration: float


class Transcript(TypedDict):
    language: str
    snippets: list[Snippet]


class YouTubeError(Exception):
    def __init__(self, code: Literal["not_found", "no_transcript", "age_restricted"], message: str):
        super().__init__(message)
        self.code = code


class YouTubeClient(Protocol):
    async def get_metadata(self, video_id: str) -> VideoMetadata: ...
    async def get_transcript(self, video_id: str) -> Transcript: ...


class ProxySettings:
    """Resolves proxy config once. Webshare secret format: {"username": "...", "password": "..."}."""

    def __init__(self, secret_name: str = "", proxy_url: str = ""):
        self._secret_name = secret_name
        self._proxy_url = proxy_url
        self._resolved: tuple[Any, str | None] | None = None

    def resolve(self) -> tuple[Any, str | None]:
        """Returns (youtube_transcript_api ProxyConfig | None, proxy URL for yt-dlp | None)."""
        if self._resolved is not None:
            return self._resolved
        from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

        if self._secret_name:
            from google.cloud import secretmanager

            try:
                client = secretmanager.SecretManagerServiceClient()
                payload = client.access_secret_version(name=self._secret_name).payload.data.decode()
                creds = json.loads(payload)
                cfg = WebshareProxyConfig(proxy_username=creds["username"], proxy_password=creds["password"])
                self._resolved = (cfg, cfg.to_requests_dict().get("https"))
            except Exception as e:  # secret missing/empty/malformed: run without a proxy rather than fail
                log.warning("YouTube proxy secret unusable (%s); continuing without a proxy", type(e).__name__)
                self._resolved = (None, None)
        elif self._proxy_url:
            self._resolved = (GenericProxyConfig(http_url=self._proxy_url, https_url=self._proxy_url), self._proxy_url)
        else:
            self._resolved = (None, None)
        return self._resolved


class LiveYouTubeClient:
    def __init__(self, proxy: ProxySettings, cache: BlobStore | None = None):
        self._proxy = proxy
        self._cache = cache

    # ---- cache helpers -------------------------------------------------
    async def _cache_get(self, path: str, ttl: int | None = None) -> Any | None:
        if self._cache is None or not await self._cache.exists(path):
            return None
        bucket = getattr(self._cache, "bucket_name", "")
        data = json.loads(await self._cache.get_text(f"gs://{bucket}/{path}"))
        if ttl is not None and time.time() - data.get("_fetched_at", 0) > ttl:
            return None
        return data["value"]

    async def _cache_put(self, path: str, value: Any) -> None:
        if self._cache is not None:
            body = json.dumps({"_fetched_at": time.time(), "value": value})
            await self._cache.put_text(path, body, content_type="application/json")

    # ---- metadata ------------------------------------------------------
    async def get_metadata(self, video_id: str) -> VideoMetadata:
        path = f"cache/videos/{video_id}/metadata.json"
        if cached := await self._cache_get(path, ttl=METADATA_TTL_SECONDS):
            return cached
        meta = await asyncio.to_thread(self._fetch_metadata, video_id)
        await self._cache_put(path, meta)
        return meta

    def _fetch_metadata(self, video_id: str) -> VideoMetadata:
        import yt_dlp

        _, proxy_url = self._proxy.resolve()
        opts: dict[str, Any] = {"quiet": True, "skip_download": True, "no_warnings": True}
        if proxy_url:
            opts["proxy"] = proxy_url
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "not a bot" in msg or "429" in msg or "blocked" in msg.lower():
                raise TransientFetchError(f"YouTube blocked the metadata request: {msg[:200]}") from e
            if "age" in msg.lower() and "restrict" in msg.lower():
                raise YouTubeError("age_restricted", "This video is age-restricted.") from e
            raise YouTubeError("not_found", f"Video unavailable: {msg[:200]}") from e
        chapters = [
            {"title": c["title"], "start": float(c["start_time"]), "end": float(c["end_time"])}
            for c in (info.get("chapters") or [])
        ]
        return {
            "video_id": video_id,
            "title": info.get("title", "") or "",
            "description": info.get("description", "") or "",
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": int(info.get("duration") or 0),
            "chapters": chapters,
            "thumbnail_url": info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        }

    # ---- transcript ----------------------------------------------------
    async def get_transcript(self, video_id: str) -> Transcript:
        path = f"cache/videos/{video_id}/transcript.json"
        if cached := await self._cache_get(path):
            return cached
        tr = await asyncio.to_thread(self._fetch_transcript, video_id)
        await self._cache_put(path, tr)
        return tr

    def _fetch_transcript(self, video_id: str) -> Transcript:
        import youtube_transcript_api as yta

        proxy_cfg, _ = self._proxy.resolve()
        api = yta.YouTubeTranscriptApi(proxy_config=proxy_cfg)
        try:
            try:
                fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
            except yta.NoTranscriptFound:
                fetched = next(iter(api.list(video_id))).fetch()
        except (yta.RequestBlocked, yta.IpBlocked, yta.YouTubeRequestFailed, yta.PoTokenRequired) as e:
            raise TransientFetchError(f"YouTube blocked the transcript request ({type(e).__name__})") from e
        except (yta.TranscriptsDisabled, yta.NoTranscriptFound, StopIteration) as e:
            raise YouTubeError("no_transcript", "This video has no captions or transcript.") from e
        except yta.AgeRestricted as e:
            raise YouTubeError("age_restricted", "This video is age-restricted.") from e
        except (yta.VideoUnavailable, yta.VideoUnplayable, yta.InvalidVideoId) as e:
            raise YouTubeError("not_found", "Video unavailable.") from e
        snippets = [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]
        if not snippets:
            raise YouTubeError("no_transcript", "Transcript is empty.")
        return {"language": getattr(fetched, "language_code", "unknown"), "snippets": snippets}
