"""Default provider: the Claude Code CLI in headless mode.

This authenticates with the user's **Claude subscription** (interactive login,
or a token from `claude setup-token` exported as CLAUDE_CODE_OAUTH_TOKEN) — no
per-token Anthropic API billing. The CLI's headless mode (`claude -p`) is the
officially supported path for subscription-auth inference today.

Requires the Claude Code CLI installed and on PATH (or BRAIN_CLAUDE_CLI_PATH).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from ..config import get_settings
from .base import LLMError


class ClaudeCliProvider:
    name = "claude_cli"

    def __init__(self) -> None:
        self._s = get_settings()

    def available(self) -> bool:
        return shutil.which(self._s.claude_cli_path) is not None

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self.available():
            raise LLMError(
                f"Claude CLI '{self._s.claude_cli_path}' not found on PATH. "
                "Install Claude Code and run `claude` to log in, or set BRAIN_LLM_PROVIDER=anthropic."
            )

        cmd = [
            self._s.claude_cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self._s.claude_model,
        ]
        if system:
            cmd += ["--append-system-prompt", system]

        env = os.environ.copy()
        if self._s.claude_code_oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._s.claude_code_oauth_token

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                # Claude emits UTF-8 (smart quotes, em-dashes, emoji). Without this, Windows
                # decodes stdout as cp1252 and raises UnicodeDecodeError, losing the output.
                encoding="utf-8",
                errors="replace",
                timeout=self._s.llm_timeout_sec,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError("Claude CLI timed out") from exc

        if proc.returncode != 0:
            raise LLMError(f"Claude CLI exited {proc.returncode}: {proc.stderr.strip()[:500]}")

        out = proc.stdout.strip()
        # `--output-format json` wraps the result; fall back to raw text otherwise.
        try:
            payload = json.loads(out)
            if isinstance(payload, dict):
                return str(payload.get("result") or payload.get("text") or out)
        except json.JSONDecodeError:
            pass
        return out
