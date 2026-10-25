"""One place that asks an AI for structured JSON. Two backends:

  mira       – Ilari's agent runtime: a miragen agent container reached over
               miragen-net. POST /run/async {prompt} → {run_id}; poll
               GET /runs/{run_id} until status is terminal; `output` is text.
               Header X-Miragen-Token when the runner guards /run.
               (Shape taken from movingfirm-admin/admin/miragen_client.py.)
  anthropic  – direct Messages API, used only when MIRA_AGENT_URL is unset.

Neither is required: with nothing configured complete_json() returns None and
callers fall back to rule-based extraction. Failures never raise."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TERMINAL_FAIL = {"failed", "interrupted", "suspended", "abandoned"}


@dataclass
class LLMResult:
    data: dict | None
    provider: str          # mira | anthropic
    raw: str | None = None
    error: str | None = None
    run_id: str | None = None


def provider() -> str | None:
    if settings.MIRA_AGENT_URL:
        return "mira"
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _mira(prompt: str, client: httpx.Client | None) -> LLMResult:
    base = settings.MIRA_AGENT_URL.rstrip("/")
    headers = {"X-Miragen-Token": settings.MIRA_AGENT_TOKEN} if settings.MIRA_AGENT_TOKEN else {}
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        try:
            r = client.post(f"{base}/run/async", json={"prompt": prompt}, headers=headers)
        except httpx.HTTPError as exc:
            return LLMResult(None, "mira", error=f"mira unreachable: {exc}")
        if r.status_code == 503:
            return LLMResult(None, "mira", error="mira agent not ready (503)")
        if r.status_code >= 400:
            return LLMResult(None, "mira", error=f"mira /run/async HTTP {r.status_code}: {r.text[:200]}")
        run_id = r.json().get("run_id")
        if not run_id:
            return LLMResult(None, "mira", error="mira returned no run_id")
        deadline = time.monotonic() + settings.MIRA_RUN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                run = client.get(f"{base}/runs/{run_id}", headers=headers).json()
            except (httpx.HTTPError, ValueError) as exc:
                return LLMResult(None, "mira", error=f"mira poll failed: {exc}", run_id=run_id)
            status = run.get("status")
            if status == "succeeded":
                output = run.get("output") or ""
                return LLMResult(_extract_json(output), "mira", raw=output, run_id=run_id,
                                 error=None if _extract_json(output) else "mira output was not JSON")
            if status in _TERMINAL_FAIL:
                return LLMResult(None, "mira", run_id=run_id,
                                 error=f"mira run {status}: {run.get('error') or run.get('exit_reason') or ''}")
            time.sleep(settings.MIRA_POLL_SECONDS)
        return LLMResult(None, "mira", run_id=run_id, error="mira run timed out")
    finally:
        if own:
            client.close()


def _anthropic(prompt: str) -> LLMResult:
    try:
        import anthropic
    except ImportError:
        return LLMResult(None, "anthropic", error="anthropic package not installed")
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(model=settings.ANTHROPIC_MODEL, max_tokens=800,
                                     messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = _extract_json(raw)
        return LLMResult(data, "anthropic", raw=raw, error=None if data else "output was not JSON")
    except Exception as exc:  # noqa: BLE001
        return LLMResult(None, "anthropic", error=str(exc)[:300])


def complete_json(prompt: str, client: httpx.Client | None = None) -> LLMResult | None:
    """Ask the configured backend for a JSON object. None when no backend is configured."""
    p = provider()
    if p == "mira":
        result = _mira(prompt, client)
    elif p == "anthropic":
        result = _anthropic(prompt)
    else:
        return None
    if result.error:
        log.warning("llm (%s): %s", result.provider, result.error)
    return result


def health() -> dict:
    """For the settings page: which backend, and is it reachable."""
    p = provider()
    info: dict = {"provider": p}
    if p == "mira":
        try:
            r = httpx.get(settings.MIRA_AGENT_URL.rstrip("/") + "/health", timeout=5.0)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            info.update(reachable=r.status_code < 500, agent=body.get("agent"), status=body.get("status"),
                        version=body.get("version"))
        except (httpx.HTTPError, ValueError) as exc:
            info.update(reachable=False, error=str(exc)[:200])
    elif p == "anthropic":
        info.update(reachable=True, model=settings.ANTHROPIC_MODEL)
    return info
