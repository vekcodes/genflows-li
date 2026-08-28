"""Render the generated image prompt into an actual LinkedIn-ready image — free models only.

The content engine already writes an image prompt per post (see `prompts.image_prompt`); this
module is the missing last mile: it calls a free, high-quality text-to-image model and returns
the bytes, so the post ships with a finished 1200x1200 visual instead of a brief to paste
somewhere else.

Providers, in the order `auto` tries them — all free, none billed:

  together      FLUX.1-schnell-Free on Together AI. Best quality/latency for a free tier.
                Free key: https://api.together.xyz/settings/api-keys -> BRAIN_TOGETHER_API_KEY
  cloudflare    @cf/black-forest-labs/flux-1-schnell on Workers AI, inside Cloudflare's free
                daily allowance. Needs BRAIN_CLOUDFLARE_ACCOUNT_ID + BRAIN_CLOUDFLARE_API_TOKEN
                (token scope: "Workers AI - Read"). Output is a fixed 1024x1024 square.
  huggingface   FLUX.1-schnell on the HF Inference API.
                Free token: https://huggingface.co/settings/tokens -> BRAIN_HUGGINGFACE_API_KEY
  pollinations  https://pollinations.ai — the only provider that needs NO credentials at all, so
                it is always the last-resort fallback. Its anonymous tier serves SANA capped at
                768px (usable, clearly below FLUX); a free token (https://auth.pollinations.ai
                -> BRAIN_POLLINATIONS_TOKEN) unlocks FLUX at the requested size.

Set any ONE of the keys above for FLUX-grade output. With none set, images still generate.

Nothing here raises into the generation loop: `agent` treats a failure as "no image yet" and the
UI offers a one-click retry.
"""
from __future__ import annotations

import base64
import logging
import random
import time
import urllib.parse
from dataclasses import dataclass

import httpx

from ..config import get_settings

log = logging.getLogger("brain.imagegen")

# Prompt text sent to the image model. FLUX degrades on very long prompts, and the useful
# detail is always at the front of ours.
MAX_PROMPT_CHARS = 1200

DEFAULT_MODELS = {
    "together": "black-forest-labs/FLUX.1-schnell-Free",
    "cloudflare": "@cf/black-forest-labs/flux-1-schnell",
    "huggingface": "black-forest-labs/FLUX.1-schnell",
    # "flux" needs a (free) token; the anonymous tier silently serves SANA instead.
    "pollinations": "flux",
}

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
)


class ImageGenError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime: str
    provider: str
    model: str
    width: int
    height: int


def _sniff_mime(data: bytes, fallback: str = "image/png") -> str:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    return fallback


def _check_image(data: bytes, *, provider: str) -> bytes:
    """Reject HTML error pages / truncated bodies that arrive with a 200."""
    if len(data) < 1024 or _sniff_mime(data, "") == "":
        snippet = data[:200].decode("utf-8", "replace").strip()
        raise ImageGenError(f"{provider} returned {len(data)} bytes of non-image data: {snippet!r}")
    return data


def available_providers() -> list[str]:
    """Providers that can run right now, best first. Pollinations needs no credentials."""
    s = get_settings()
    out: list[str] = []
    if s.together_api_key:
        out.append("together")
    if s.cloudflare_account_id and s.cloudflare_api_token:
        out.append("cloudflare")
    if s.huggingface_api_key:
        out.append("huggingface")
    out.append("pollinations")   # no credentials required — always the fallback
    return out


def _resolve_providers() -> list[str]:
    s = get_settings()
    if not s.image_gen_enabled or s.image_provider == "none":
        return []
    if s.image_provider == "auto":
        return available_providers()
    return [s.image_provider]


def _round16(n: int) -> int:
    """FLUX endpoints want multiples of 16; keep it inside their supported range."""
    return max(256, min(1440, round(n / 16) * 16))


# ---- Providers ----

def _via_together(prompt: str, width: int, height: int, seed: int) -> GeneratedImage:
    s = get_settings()
    model = s.image_model or DEFAULT_MODELS["together"]
    res = httpx.post(
        "https://api.together.xyz/v1/images/generations",
        headers={"Authorization": f"Bearer {s.together_api_key}"},
        json={
            "model": model,
            "prompt": prompt,
            "width": _round16(width),
            "height": _round16(height),
            "steps": 4,          # schnell is a 4-step distilled model
            "n": 1,
            "seed": seed,
            "response_format": "b64_json",
        },
        timeout=s.image_timeout_sec,
    )
    if res.status_code >= 400:
        raise ImageGenError(f"together {res.status_code}: {res.text[:300]}")
    payload = (res.json().get("data") or [{}])[0]
    b64 = payload.get("b64_json")
    if not b64:
        url = payload.get("url")
        if not url:
            raise ImageGenError("together returned neither b64_json nor url")
        data = httpx.get(url, timeout=s.image_timeout_sec).content
    else:
        data = base64.b64decode(b64)
    data = _check_image(data, provider="together")
    return GeneratedImage(data, _sniff_mime(data), "together", model, width, height)


def _via_cloudflare(prompt: str, width: int, height: int, seed: int) -> GeneratedImage:
    """Workers AI FLUX.1-schnell. Fixed 1024x1024 output — the UI rescales to the target size.

    `seed` is accepted for signature parity with the other providers but deliberately not sent:
    this endpoint validates its input strictly and rejects unknown keys, so including it fails
    every call with `AiError: Bad input: Additional or unevaluated properties '/seed'` (400).
    Retries therefore vary by the model's own randomness rather than by seed.
    """
    s = get_settings()
    model = s.image_model or DEFAULT_MODELS["cloudflare"]
    res = httpx.post(
        f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}/ai/run/{model}",
        headers={"Authorization": f"Bearer {s.cloudflare_api_token}"},
        json={"prompt": prompt, "steps": 8},   # 8 is the endpoint maximum; 12 is rejected
        timeout=s.image_timeout_sec,
    )
    if res.status_code >= 400:
        raise ImageGenError(f"cloudflare {res.status_code}: {res.text[:300]}")
    body = res.json()
    if not body.get("success", True):
        raise ImageGenError(f"cloudflare: {str(body.get('errors'))[:300]}")
    b64 = (body.get("result") or {}).get("image")
    if not b64:
        raise ImageGenError("cloudflare returned no image field")
    data = _check_image(base64.b64decode(b64), provider="cloudflare")
    return GeneratedImage(data, _sniff_mime(data, "image/jpeg"), "cloudflare", model, 1024, 1024)


def _via_huggingface(prompt: str, width: int, height: int, seed: int) -> GeneratedImage:
    s = get_settings()
    model = s.image_model or DEFAULT_MODELS["huggingface"]
    res = httpx.post(
        f"https://router.huggingface.co/hf-inference/models/{model}",
        headers={
            "Authorization": f"Bearer {s.huggingface_api_key}",
            "Accept": "image/png",
        },
        json={
            "inputs": prompt,
            "parameters": {"width": _round16(width), "height": _round16(height), "seed": seed},
        },
        timeout=s.image_timeout_sec,
    )
    if res.status_code == 503:
        # Cold model on the free tier: HF reports an estimated warm-up time.
        raise ImageGenError("huggingface model is loading (503) — retry shortly")
    if res.status_code >= 400:
        raise ImageGenError(f"huggingface {res.status_code}: {res.text[:300]}")
    data = _check_image(res.content, provider="huggingface")
    return GeneratedImage(data, _sniff_mime(data, res.headers.get("content-type", "image/png")),
                          "huggingface", model, width, height)


def _via_pollinations(prompt: str, width: int, height: int, seed: int) -> GeneratedImage:
    """No key required: the prompt is the URL path, the image is the response body.

    Anonymous requests are served SANA at up to 768px whichever model is asked for; a free
    token (BRAIN_POLLINATIONS_TOKEN) unlocks FLUX at the requested size.
    """
    s = get_settings()
    model = s.image_model or DEFAULT_MODELS["pollinations"]
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt, safe="")
    headers = {"Authorization": f"Bearer {s.pollinations_token}"} if s.pollinations_token else {}
    res = httpx.get(
        url,
        headers=headers,
        params={
            "width": width,
            "height": height,
            "model": model,
            "seed": seed,
            "nologo": "true",
            "safe": "false",
            "referrer": "genflows-linkedin-engine",
        },
        timeout=s.image_timeout_sec,
        follow_redirects=True,
    )
    if res.status_code >= 400:
        raise ImageGenError(f"pollinations {res.status_code}: {res.text[:300]}")
    data = _check_image(res.content, provider="pollinations")
    return GeneratedImage(data, _sniff_mime(data, res.headers.get("content-type", "image/jpeg")),
                          "pollinations", model, width, height)


_PROVIDERS = {
    "together": _via_together,
    "cloudflare": _via_cloudflare,
    "huggingface": _via_huggingface,
    "pollinations": _via_pollinations,
}


# ---- Public entry point ----

def generate(
    prompt: str,
    *,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
) -> GeneratedImage:
    """Render `prompt` with the first free provider that succeeds.

    Tries each resolved provider up to `image_max_retries + 1` times (free endpoints rate-limit
    and cold-start), then moves on to the next. Raises ImageGenError only if all of them fail.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("empty image prompt")

    s = get_settings()
    providers = _resolve_providers()
    if not providers:
        raise ImageGenError("image generation is disabled (BRAIN_IMAGE_GEN_ENABLED / IMAGE_PROVIDER)")

    width = width or s.image_width
    height = height or s.image_height
    seed = seed if seed is not None else random.randint(1, 2_000_000_000)
    body = prompt[:MAX_PROMPT_CHARS]

    errors: list[str] = []
    for name in providers:
        fn = _PROVIDERS.get(name)
        if fn is None:
            errors.append(f"{name}: unknown provider")
            continue
        for attempt in range(s.image_max_retries + 1):
            try:
                img = fn(body, width, height, seed + attempt)
                log.info("image generated via %s/%s (%s bytes)", img.provider, img.model, len(img.data))
                return img
            except (ImageGenError, httpx.HTTPError) as exc:
                errors.append(f"{name}: {exc}")
                log.info("image provider %s attempt %s failed: %s", name, attempt + 1, exc)
                if attempt < s.image_max_retries:
                    time.sleep(2.0 * (attempt + 1))

    raise ImageGenError("all image providers failed — " + " | ".join(errors[-4:]))
