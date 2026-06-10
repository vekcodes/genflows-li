"""Transcript fetching via youtube-transcript-api (primary).

YouTube IP-blocks transcript requests after volume; set BRAIN_TRANSCRIPT_PROXY to route through
a proxy (the library's documented fix). faster-whisper is the no-caption fallback but pulls in
torch, so it's left as an opt-in extension.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session, select

from ..config import get_settings
from .. import vectorstore
from ..models import Transcript, Video
from ..throttle import jittered_delay

log = logging.getLogger("brain.transcripts")

# Set to the last caption-fetch failure reason (e.g. "IpBlocked") so a bulk pass can react.
last_error: str | None = None

_whisper_model = None  # lazily-loaded faster-whisper model (cached process-wide)


@dataclass
class TranscriptResult:
    lang: str | None
    provider: str
    text: str
    segments_json: str


def _api():
    """Build a YouTubeTranscriptApi instance, with a proxy if configured."""
    from youtube_transcript_api import YouTubeTranscriptApi

    proxy = get_settings().transcript_proxy
    if proxy:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig

            return YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=proxy, https_url=proxy))
        except Exception as exc:  # pragma: no cover - bad proxy config
            log.warning("transcript proxy config failed (%s); going direct", exc)
    return YouTubeTranscriptApi()


def _caption_transcript(video_id: str) -> TranscriptResult | None:
    """Fast path: YouTube captions via youtube-transcript-api (honours the proxy)."""
    global last_error
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:  # pragma: no cover
        return None
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):  # older module-level API
            segments = YouTubeTranscriptApi.get_transcript(video_id)
        else:  # newer instance API (supports proxies)
            fetched = _api().fetch(video_id)
            segments = [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]
    except Exception as exc:
        last_error = type(exc).__name__  # IpBlocked / TranscriptsDisabled / NoTranscriptFound / ...
        log.warning("caption fetch failed for %s: %s", video_id, last_error)
        return None
    last_error = None
    text = " ".join(s.get("text", "") for s in segments).strip()
    return TranscriptResult(lang=None, provider="api", text=text, segments_json=json.dumps(segments, ensure_ascii=False))


def _get_whisper():
    """Lazily load (and cache) the faster-whisper model, using all CPU cores."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        s = get_settings()
        threads = max(4, os.cpu_count() or 4)
        log.info("loading whisper model %s (%s, %s threads)…", s.whisper_model, s.whisper_compute_type, threads)
        _whisper_model = WhisperModel(
            s.whisper_model, device="cpu", compute_type=s.whisper_compute_type, cpu_threads=threads
        )
    return _whisper_model


def _download_audio(video_id: str) -> str | None:
    """Download bestaudio to a temp file (the audio CDN isn't caption-rate-limited)."""
    from yt_dlp import YoutubeDL

    s = get_settings()
    tmp = tempfile.mkdtemp(prefix="brain_audio_")
    opts: dict = {
        "quiet": True, "noprogress": True, "ignoreerrors": True,
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
        # Hard limits so a throttled/stalled CDN connection can't hang the worker forever.
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
    }
    if s.transcript_proxy:
        opts["proxy"] = s.transcript_proxy
    with YoutubeDL(opts) as y:
        y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    files = glob.glob(os.path.join(tmp, f"{video_id}.*"))
    return files[0] if files else None


def _whisper_transcript(video_id: str) -> TranscriptResult | None:
    """Block-proof fallback: transcribe the downloaded audio locally with faster-whisper."""
    path = None
    try:
        path = _download_audio(video_id)
        if not path:
            return None
        model = _get_whisper()
        # beam_size=1 (greedy) + VAD (skip silence) — much faster, plenty good for style mining.
        segments_gen, _info = model.transcribe(path, beam_size=1, vad_filter=True, condition_on_previous_text=False)
        segs = [{"text": s.text.strip(), "start": round(s.start, 2), "duration": round(s.end - s.start, 2)} for s in segments_gen]
        text = " ".join(s["text"] for s in segs).strip()
        if not text:
            return None
        return TranscriptResult(lang="en", provider="whisper", text=text, segments_json=json.dumps(segs, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - whisper/model/audio failure
        log.warning("whisper transcription failed for %s: %s", video_id, exc)
        return None
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                os.rmdir(os.path.dirname(path))
            except OSError:
                pass


def _apify_transcript(video_id: str) -> TranscriptResult | None:
    """Hosted captions via Apify (residential proxies bypass the IP-block). None on any error."""
    global last_error
    try:
        from . import apify

        result = apify.fetch_transcript(video_id)
        if result and result.text:
            last_error = None
            return result
    except Exception as exc:  # noqa: BLE001 - degrade to the local caption/Whisper path
        last_error = type(exc).__name__
        log.warning("Apify transcript failed for %s: %s", video_id, last_error)
    return None


def fetch_transcript(video_id: str, *, allow_whisper: bool = False) -> TranscriptResult | None:
    """Transcript for a video: Apify (when enabled) → captions → Whisper (when allowed).

    Apify runs behind residential proxies, so it sidesteps the caption IP-block entirely.
    Whisper is the block-proof local fallback but is CPU-heavy, so it only runs when explicitly
    allowed (the "Retry transcripts" backfill) — never inline during a normal scrape, which
    must stay fast. Also gated by BRAIN_TRANSCRIPT_WHISPER_ENABLED.
    """
    from . import apify

    if apify.transcripts_enabled():
        result = _apify_transcript(video_id)
        if result and result.text:
            return result

    result = _caption_transcript(video_id)
    if result and result.text:
        return result
    if allow_whisper and get_settings().transcript_whisper_enabled:
        return _whisper_transcript(video_id)
    return result


def backfill_missing(
    session: Session,
    *,
    channel_id: str | None = None,
    limit: int = 300,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Re-fetch transcripts for videos that don't have one yet (e.g. after an IP block clears).

    Only touches the transcript layer — no re-scraping of metadata/comments. Stops early if
    YouTube starts IP-blocking again, so it doesn't pointlessly hammer a blocked IP.
    """
    report = on_progress or (lambda _d, _t, _m: None)
    settings = get_settings()

    # Most-viewed first — the videos that matter most for style cards get transcribed first.
    q = select(Video).where(Video.has_transcript == False).order_by(Video.views.desc())  # noqa: E712
    if channel_id:
        q = q.where(Video.channel_id == channel_id)
    videos = list(session.exec(q).all())[:limit]

    total = len(videos)
    cap = settings.whisper_max_duration_sec
    fetched = blocked = unavailable = 0
    report(0, total, f"{total} videos missing transcripts")
    for i, v in enumerate(videos):
        # Skip very long videos (livestreams/masterclasses) — bounds CPU per item.
        if v.duration_sec and v.duration_sec > cap:
            unavailable += 1
            report(i + 1, total, f"{fetched} fetched · skipped 1 long video")
            continue
        tr = fetch_transcript(v.id, allow_whisper=True)  # backfill may use the Whisper fallback
        if tr and tr.text:
            existing = session.get(Transcript, v.id)
            if existing:
                existing.text = tr.text
                existing.segments_json = tr.segments_json
                session.add(existing)
            else:
                session.add(Transcript(video_id=v.id, lang=tr.lang, provider=tr.provider,
                                       text=tr.text, segments_json=tr.segments_json))
            v.has_transcript = True
            session.add(v)
            vectorstore.index_video(session, v.id, tr.text)
            session.commit()
            fetched += 1
        elif last_error == "IpBlocked" and not settings.transcript_whisper_enabled:
            blocked += 1
            # Bail out — the caption IP is blocked and there's no Whisper fallback to recover.
            report(i + 1, total, "YouTube is IP-blocking transcripts — stopped")
            break
        else:
            unavailable += 1
        report(i + 1, total, f"{fetched} fetched · {unavailable} no-captions")
        jittered_delay(settings.scrape_min_delay_sec, settings.scrape_max_delay_sec)

    return {"total": total, "fetched": fetched, "unavailable": unavailable, "blocked": blocked}
