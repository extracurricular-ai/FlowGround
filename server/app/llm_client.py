"""Minimal async client for the two LLM wire shapes "llm_generate"/"llm_judge"
need — text in, text out, nothing multimodal.

Two compatibility modes, chosen by the user's global AI settings (never part
of a flow's own config — see PROTOCOL.md "llm" field on the start message):

- ``"anthropic"``: POST ``{base_url}/v1/messages``, ``x-api-key`` header.
- ``"openai"``: POST ``{base_url}/chat/completions``, ``Authorization: Bearer``
  header — matches the OpenAI Chat Completions shape most compatible
  providers (local servers, third-party gateways) also speak.
"""

from __future__ import annotations

from typing import Any, Dict

import httpx

#: generous but bounded — a hung LLM endpoint must not hang a run forever.
REQUEST_TIMEOUT = 45.0
#: Anthropic requires this; there's no per-node config for it in this MVP.
ANTHROPIC_MAX_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(Exception):
    """A friendly-message failure calling the configured LLM endpoint."""


def _request_for(mode: str, base_url: str, api_key: str, model: str, prompt: str):
    base = (base_url or "").rstrip("/")
    if mode == "anthropic":
        url = base + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        return url, headers, body
    # "openai" (default): OpenAI itself and most OpenAI-compatible endpoints.
    url = base + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    return url, headers, body


def _extract_text(mode: str, data: Any) -> str:
    try:
        if mode == "anthropic":
            return data["content"][0]["text"]
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"got back a response that doesn’t look like {mode}’s shape "
            f"({exc}) — check the compat mode in AI settings"
        ) from exc


async def call_llm(*, mode: str, base_url: str, api_key: str, model: str,
                   prompt: str) -> str:
    """Call the configured LLM endpoint and return its text reply.

    Raises :class:`LLMError` with a message meant to be shown verbatim in the
    run console (network failure, non-2xx status, or an unrecognized
    response shape for the chosen compat mode).
    """
    if not api_key:
        raise LLMError("no API key set — open AI settings and add one")
    if not base_url:
        raise LLMError("no base URL set — open AI settings and add one")
    url, headers, body = _request_for(mode, base_url, api_key, model, prompt)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise LLMError(f"couldn’t reach {url} ({exc})") from exc
    if resp.status_code != 200:
        raise LLMError(f"{url} returned {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"{url} didn’t return valid JSON ({exc})") from exc
    return _extract_text(mode, data)
