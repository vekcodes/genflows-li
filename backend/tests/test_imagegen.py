"""Post-image rendering — free-provider selection, fallback, persistence and the API routes.

No network: every provider function is swapped for a stub that returns a tiny valid PNG.

Run:  PYTHONPATH=. .venv/bin/python tests/test_imagegen.py     (or via pytest)
"""
from __future__ import annotations

import base64
import os

os.environ.setdefault("BRAIN_LLM_PROVIDER", "none")

# A 1x1 PNG — enough to prove bytes survive the round trip, but _check_image demands >=1KB,
# so pad it out the way a real render would be.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DAwAAABQABc"
    "xr3lgAAAABJRU5ErkJggg=="
) + b"\x00" * 2048


class _Swap:
    """Temporarily set object attributes / env vars, restoring them on exit."""

    def __init__(self):
        self._attrs: list[tuple[object, str, object]] = []
        self._env: list[tuple[str, str | None]] = []

    def attr(self, obj, name, value):
        self._attrs.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def env(self, name, value):
        self._env.append((name, os.environ.get(name)))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
        from app.config import get_settings

        get_settings.cache_clear()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        for obj, name, old in reversed(self._attrs):
            setattr(obj, name, old)
        for name, old in reversed(self._env):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        from app.config import get_settings

        get_settings.cache_clear()
        return False


def _stub(data: bytes = PNG, *, provider: str = "pollinations", model: str = "flux"):
    from app.generation import imagegen, prompts

    def _fn(prompt, width, height, seed):
        assert prompt, "provider called with an empty prompt"
        return imagegen.GeneratedImage(data, "image/png", provider, model, width, height)

    return _fn


def _boom(message: str):
    from app.generation import imagegen

    def _fn(prompt, width, height, seed):
        raise imagegen.ImageGenError(message)

    return _fn


def _session():
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    # StaticPool: TestClient serves requests on another thread, and a per-thread in-memory
    # SQLite would hand that thread a fresh, empty database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _item(session):
    from app.models import ContentItem

    item = ContentItem(
        batch_id="b1",
        title="7 cold email mistakes",
        thumbnail_prompt="navy #0A1F35 pipeline line-art, one orange #E67E22 node, no text",
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# ---- provider selection & fallback ----

def test_auto_prefers_keyed_providers():
    from app.generation import imagegen

    with _Swap() as sw:
        sw.env("BRAIN_TOGETHER_API_KEY", None)
        sw.env("BRAIN_HUGGINGFACE_API_KEY", None)
        assert imagegen.available_providers() == ["pollinations"]
        sw.env("BRAIN_TOGETHER_API_KEY", "tok")
        assert imagegen.available_providers() == ["together", "pollinations"]
        sw.env("BRAIN_CLOUDFLARE_ACCOUNT_ID", "acct")
        assert imagegen.available_providers() == ["together", "pollinations"]  # token missing
        sw.env("BRAIN_CLOUDFLARE_API_TOKEN", "cf")
        assert imagegen.available_providers() == ["together", "cloudflare", "pollinations"]
        sw.env("BRAIN_HUGGINGFACE_API_KEY", "hf")
        assert imagegen.available_providers() == [
            "together", "cloudflare", "huggingface", "pollinations",
        ]
    print("provider selection (free by default, keyed first): ok")


def test_falls_back_to_next_provider():
    from app.generation import imagegen

    with _Swap() as sw:
        sw.env("BRAIN_TOGETHER_API_KEY", "tok")
        sw.env("BRAIN_HUGGINGFACE_API_KEY", None)
        sw.env("BRAIN_IMAGE_MAX_RETRIES", "0")
        sw.attr(imagegen, "_PROVIDERS", {
            "together": _boom("rate limited"),
            "pollinations": _stub(),
        })
        img = imagegen.generate("a prompt", width=1200, height=1200)
        assert img.provider == "pollinations" and img.data == PNG
        assert (img.width, img.height) == (1200, 1200)
    print("provider fallback: ok")


def test_all_providers_failing_raises():
    from app.generation import imagegen

    with _Swap() as sw:
        sw.env("BRAIN_IMAGE_MAX_RETRIES", "0")
        sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
        sw.attr(imagegen, "_PROVIDERS", {"pollinations": _boom("503 upstream")})
        try:
            imagegen.generate("a prompt")
        except imagegen.ImageGenError as exc:
            assert "503 upstream" in str(exc)
        else:
            raise AssertionError("expected ImageGenError")
    print("all-providers-failed surfaces the error: ok")


def test_rejects_non_image_body():
    from app.generation import imagegen

    with _Swap() as sw:
        sw.env("BRAIN_IMAGE_MAX_RETRIES", "0")
        sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
        sw.attr(imagegen, "_PROVIDERS", {"pollinations": lambda *a: _raise_html()})
        try:
            imagegen.generate("a prompt")
        except imagegen.ImageGenError:
            pass
        else:
            raise AssertionError("an HTML error page must not pass as an image")
    print("non-image response rejected: ok")


def _raise_html():
    from app.generation import imagegen

    return imagegen._check_image(b"<html>rate limit</html>", provider="pollinations")


# ---- persistence ----

def test_render_image_persists_bytes():
    from app import agent
    from app.generation import imagegen

    session = _session()
    item = _item(session)

    with _Swap() as sw:
        sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
        sw.attr(imagegen, "_PROVIDERS", {"pollinations": _stub()})
        row = agent.render_image(session, item.id, overlay_text="STOP GUESSING", accent_word="GUESSING")

    assert row.status == "ready", row.error
    assert row.data == PNG and row.bytes_len == len(PNG)
    assert row.mime == "image/png" and row.provider == "pollinations"
    assert (row.width, row.height) == (1200, 1200)  # the LinkedIn target, not the provider's size
    assert row.overlay_text == "STOP GUESSING" and row.accent_word == "GUESSING"
    assert row.prompt == item.thumbnail_prompt  # defaults to the item's generated prompt
    print("render_image persists bytes + brand overlay fields: ok")


def test_render_image_records_failure_without_raising():
    from app import agent
    from app.generation import imagegen

    session = _session()
    item = _item(session)

    with _Swap() as sw:
        sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
        sw.env("BRAIN_IMAGE_MAX_RETRIES", "0")
        sw.attr(imagegen, "_PROVIDERS", {"pollinations": _boom("quota exhausted")})
        row = agent.render_image(session, item.id)

    assert row.status == "error" and "quota exhausted" in row.error
    assert not row.data
    print("render failure is recorded, never raised into generation: ok")


def test_generation_attaches_image_brief():
    """A generated batch stores the visual brief even when rendering is switched off."""
    import json

    from app import agent
    from app.generation import prompts
    from app.models import ContentImage

    class FakeLLM:
        name = "fake"

        def available(self) -> bool:
            return True

        def complete(self, prompt: str, *, system: str | None = None) -> str:
            if "stronger idea" in prompt:
                return json.dumps({"title": "Cold email mistakes", "angle": "fix them",
                                   "format": "listicle", "evidence": []})
            if "LinkedIn post ideas" in prompt:
                return json.dumps([{"title": "Cold email mistakes", "angle": "fix them",
                                    "format": "listicle", "evidence": []}])
            if "Plan the post as ordered sections" in prompt:
                return json.dumps([{"beat": "Hook", "heading": "open", "intent": "hook"},
                                   {"beat": "CTA", "heading": "close", "intent": "ask"}])
            if "render_prompt" in prompt:
                return json.dumps({
                    "render_prompt": "navy pipeline line-art, orange node, no text, no logos",
                    "overlay_text": "STOP GUESSING",
                    "accent_word": "GUESSING",
                })
            return "text"

    session = _session()
    with _Swap() as sw:
        sw.env("BRAIN_IMAGE_GEN_ENABLED", "false")
        [item] = agent.generate_batch(session, llm=FakeLLM(), n=1, refresh=False)
        row = session.get(ContentImage, item.id)

    assert row is not None, "no image row created for the generated item"
    # The model writes the subject; the framing rules are appended in code (see
    # prompts.COMPOSITION_TAIL), because the model reliably filled the lower third that the
    # headline is composited into.
    assert item.thumbnail_prompt.startswith("navy pipeline line-art, orange node, no text, no logos")
    assert item.thumbnail_prompt.endswith(prompts.COMPOSITION_TAIL)
    assert row.overlay_text == "STOP GUESSING" and row.accent_word == "GUESSING"
    assert row.status == "error" and "disabled" in row.error
    print("generation attaches the visual brief: ok")


def test_image_brief_falls_back_on_bad_json():
    from app import agent

    class Prose:
        name = "fake"

        def available(self) -> bool:
            return True

        def complete(self, prompt: str, *, system: str | None = None) -> str:
            return "Sure! Here is a nice image idea for you."

    from app.generation import prompts

    brief = agent._image_brief(Prose(), "7 cold email mistakes", "fix them", "post text")
    render = brief["render_prompt"]
    # The fallback obeys the same rules as the model-written prompt: it carries the framing tail,
    # never says "no text" (naming text is what makes FLUX draw it), and never interpolates the
    # post title -- feeding words to a text-to-image model is the surest way to get lettering.
    assert render.endswith(prompts.COMPOSITION_TAIL)
    assert "no text" not in render.lower()
    assert "7 cold email mistakes" not in render
    print("image brief falls back when the LLM returns prose: ok")


# ---- API routes ----

def test_image_api_routes():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.api import content as content_api
    from app.db import get_session
    from app.generation import imagegen
    from app.main import app

    # StaticPool: TestClient serves requests on another thread, and a per-thread in-memory
    # SQLite would hand that thread a fresh, empty database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    item = _item(session)

    app.dependency_overrides[get_session] = lambda: session
    try:
        with _Swap() as sw:
            sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
            sw.attr(imagegen, "_PROVIDERS", {"pollinations": _stub()})
            client = TestClient(app)

            assert client.get(f"/content/{item.id}/image").status_code == 404  # nothing rendered yet

            res = client.post(f"/content/{item.id}/image", json={"width": 1200, "height": 628})
            assert res.status_code == 200, res.text
            meta = res.json()
            assert meta["status"] == "ready" and meta["provider"] == "pollinations"
            assert "data" not in meta, "image bytes must not ride along in the JSON payload"

            res = client.get(f"/content/{item.id}/image")
            assert res.status_code == 200 and res.content == PNG
            assert res.headers["content-type"] == "image/png"
            assert f"linkedin-post-{item.id}.png" in res.headers["content-disposition"]

            listed = client.get("/content/queue").json()
            assert listed[0]["image"]["status"] == "ready"
            assert client.get(f"/content/{item.id}").json()["image"]["bytes_len"] == len(PNG)
    finally:
        app.dependency_overrides.pop(get_session, None)
    print("image API routes (POST render, GET bytes, queue metadata): ok")


def test_image_api_reports_provider_failure():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.db import get_session
    from app.generation import imagegen
    from app.main import app

    # StaticPool: TestClient serves requests on another thread, and a per-thread in-memory
    # SQLite would hand that thread a fresh, empty database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    item = _item(session)

    app.dependency_overrides[get_session] = lambda: session
    try:
        with _Swap() as sw:
            sw.env("BRAIN_IMAGE_PROVIDER", "pollinations")
            sw.env("BRAIN_IMAGE_MAX_RETRIES", "0")
            sw.attr(imagegen, "_PROVIDERS", {"pollinations": _boom("upstream 429")})
            res = TestClient(app).post(f"/content/{item.id}/image")
            assert res.status_code == 502, res.status_code
            assert "upstream 429" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)
    print("image API surfaces provider failures as 502: ok")


if __name__ == "__main__":
    test_auto_prefers_keyed_providers()
    test_falls_back_to_next_provider()
    test_all_providers_failing_raises()
    test_rejects_non_image_body()
    test_render_image_persists_bytes()
    test_render_image_records_failure_without_raising()
    test_generation_attaches_image_brief()
    test_image_brief_falls_back_on_bad_json()
    test_image_api_routes()
    test_image_api_reports_provider_failure()
    print("\nALL IMAGE TESTS PASSED")
