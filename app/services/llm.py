"""One place that asks an AI for structured JSON. Backends, in order of preference:

  mirarun    – the hub. Agent sessions API (mirarun ADR-035):
               POST /api/agent-sessions {agent, idempotency_key, prompt}
               → poll GET /api/agent-sessions/{id} until the turn is terminal
               → POST /api/agent-sessions/{id}/close.
               Auth: Bearer MIRARUN_SESSION_TOKEN (an entry in mirarun's
               MIRARUN_SESSION_CLIENT_TOKENS with a MIRARUN_SESSION_CLIENT_POLICIES
               policy naming Luuri's agents, customer_facing=false).
               This is the path that keeps working when agents move to
               Kubernetes spokes: the hub routes the turn, Luuri never needs
               to know where the agent runs.
  miragen    – legacy: call one agent container directly on miragen-net
               (POST /run/async, poll /runs/{id}, X-Miragen-Token).
  anthropic  – direct Messages API, only when nothing above is configured.

Each call names a *task* (prospect | call_analysis | funnel_insights); the
task picks the agent name on the hub. With nothing configured
complete_json() returns None and callers fall back to rules. Never raises."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TERMINAL_FAIL = {"failed", "interrupted", "suspended", "abandoned", "cancelled"}

TASK_AGENTS = {
    "prospect": lambda: settings.MIRA_PROSPECTOR_AGENT,
    "call_analysis": lambda: settings.MIRA_CALL_ANALYST_AGENT,
    "funnel_insights": lambda: settings.MIRA_FUNNEL_ANALYST_AGENT,
}


@dataclass
class LLMResult:
    data: dict | None
    provider: str          # mirarun | miragen | anthropic
    raw: str | None = None
    error: str | None = None
    run_id: str | None = None
    agent: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def provider() -> str | None:
    if settings.MIRARUN_URL and settings.MIRARUN_SESSION_TOKEN:
        return "mirarun"
    if settings.MIRA_AGENT_URL:
        return "miragen"
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def extract_json(text: str) -> dict | None:
    """First balanced {...} object in the text. Tolerates a fenced block or a
    sentence around it, which a model sometimes adds despite instructions."""
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        return parsed if isinstance(parsed, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


# ---------------------------------------------------------------- mirarun hub
def _mirarun(prompt: str, agent: str, key: str, client: httpx.Client) -> LLMResult:
    base = settings.MIRARUN_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.MIRARUN_SESSION_TOKEN}"}
    try:
        r = client.post(f"{base}/api/agent-sessions", headers=headers,
                        json={"agent": agent, "idempotency_key": key[:180], "title": f"luuri {key[:60]}", "prompt": prompt[:200_000]})
    except httpx.HTTPError as exc:
        return LLMResult(None, "mirarun", agent=agent, error=f"mirarun unreachable: {exc}")
    if r.status_code in (401, 403):
        return LLMResult(None, "mirarun", agent=agent, error=f"mirarun refused Luuri ({r.status_code}): check MIRARUN_SESSION_CLIENT_TOKENS/POLICIES")
    if r.status_code == 429:
        return LLMResult(None, "mirarun", agent=agent, error="agent at capacity (429) – retry later")
    if r.status_code >= 400:
        return LLMResult(None, "mirarun", agent=agent, error=f"mirarun HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    session_id = body["session"]["id"]
    turn_id = (body.get("turn") or {}).get("id")
    deadline = time.monotonic() + settings.MIRA_RUN_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                detail = client.get(f"{base}/api/agent-sessions/{session_id}", headers=headers).json()
            except (httpx.HTTPError, ValueError) as exc:
                return LLMResult(None, "mirarun", agent=agent, run_id=session_id, error=f"mirarun poll failed: {exc}")
            turns = detail.get("turns") or []
            turn = next((t for t in turns if t.get("id") == turn_id), turns[0] if turns else None)
            status = (turn or {}).get("status")
            if status == "succeeded":
                out = turn.get("output") or ""
                data = extract_json(out)
                return LLMResult(data, "mirarun", raw=out, run_id=session_id, agent=agent, model=turn.get("model"),
                                 input_tokens=turn.get("input_tokens"), output_tokens=turn.get("output_tokens"),
                                 error=None if data else "agent output was not JSON")
            if status in _TERMINAL_FAIL:
                return LLMResult(None, "mirarun", run_id=session_id, agent=agent, error=f"turn {status}: {turn.get('error') or ''}")
            time.sleep(settings.MIRA_POLL_SECONDS)
        return LLMResult(None, "mirarun", run_id=session_id, agent=agent, error="agent turn timed out")
    finally:
        # One prompt, one session: close it so it doesn't sit until the idle sweep.
        try:
            client.post(f"{base}/api/agent-sessions/{session_id}/close", headers=headers, json={"reason": "done"})
        except httpx.HTTPError:
            pass


# ---------------------------------------------------------------- miragen direct (legacy)
def _miragen(prompt: str, client: httpx.Client) -> LLMResult:
    base = settings.MIRA_AGENT_URL.rstrip("/")
    headers = {"X-Miragen-Token": settings.MIRA_AGENT_TOKEN} if settings.MIRA_AGENT_TOKEN else {}
    try:
        r = client.post(f"{base}/run/async", json={"prompt": prompt}, headers=headers)
    except httpx.HTTPError as exc:
        return LLMResult(None, "miragen", error=f"mira unreachable: {exc}")
    if r.status_code == 503:
        return LLMResult(None, "miragen", error="mira agent not ready (503)")
    if r.status_code >= 400:
        return LLMResult(None, "miragen", error=f"mira /run/async HTTP {r.status_code}: {r.text[:200]}")
    run_id = r.json().get("run_id")
    if not run_id:
        return LLMResult(None, "miragen", error="mira returned no run_id")
    deadline = time.monotonic() + settings.MIRA_RUN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            run = client.get(f"{base}/runs/{run_id}", headers=headers).json()
        except (httpx.HTTPError, ValueError) as exc:
            return LLMResult(None, "miragen", error=f"mira poll failed: {exc}", run_id=run_id)
        status = run.get("status")
        if status == "succeeded":
            output = run.get("output") or ""
            data = extract_json(output)
            return LLMResult(data, "miragen", raw=output, run_id=run_id, error=None if data else "mira output was not JSON")
        if status in _TERMINAL_FAIL:
            return LLMResult(None, "miragen", run_id=run_id, error=f"mira run {status}: {run.get('error') or run.get('exit_reason') or ''}")
        time.sleep(settings.MIRA_POLL_SECONDS)
    return LLMResult(None, "miragen", run_id=run_id, error="mira run timed out")


# ---------------------------------------------------------------- anthropic direct
def _anthropic(prompt: str) -> LLMResult:
    try:
        import anthropic
    except ImportError:
        return LLMResult(None, "anthropic", error="anthropic package not installed")
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(model=settings.ANTHROPIC_MODEL, max_tokens=2000,
                                     messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = extract_json(raw)
        return LLMResult(data, "anthropic", raw=raw, model=settings.ANTHROPIC_MODEL,
                         error=None if data else "output was not JSON")
    except Exception as exc:  # noqa: BLE001
        return LLMResult(None, "anthropic", error=str(exc)[:300])


def complete_json(prompt: str, task: str = "prospect", key: str | None = None,
                  client: httpx.Client | None = None) -> LLMResult | None:
    """Ask the configured backend for a JSON object. None when no backend is configured.

    `key` is the idempotency key on the hub; a retry with the same key gets the
    same session back instead of a second paid run."""
    p = provider()
    if p is None:
        return None
    key = key or hashlib.sha256(f"{task}:{prompt}".encode()).hexdigest()[:40]
    own = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        if p == "mirarun":
            result = _mirarun(prompt, TASK_AGENTS[task](), f"luuri:{task}:{key}", client)
        elif p == "miragen":
            result = _miragen(prompt, client)
        else:
            result = _anthropic(prompt)
    finally:
        if own:
            client.close()
    if result.error:
        log.warning("llm (%s/%s): %s", result.provider, task, result.error)
    return result


def health() -> dict:
    """For the settings page: which backend, and is it reachable."""
    p = provider()
    info: dict = {"provider": p}
    if p == "mirarun":
        info["agents"] = {t: f() for t, f in TASK_AGENTS.items()}
        try:
            r = httpx.get(settings.MIRARUN_URL.rstrip("/") + "/api/agent-sessions", params={"limit": 1},
                          headers={"Authorization": f"Bearer {settings.MIRARUN_SESSION_TOKEN}"}, timeout=5.0)
            info.update(reachable=r.status_code < 400, http=r.status_code)
        except httpx.HTTPError as exc:
            info.update(reachable=False, error=str(exc)[:200])
    elif p == "miragen":
        try:
            r = httpx.get(settings.MIRA_AGENT_URL.rstrip("/") + "/health", timeout=5.0)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            info.update(reachable=r.status_code < 500, agent=body.get("agent"), status=body.get("status"))
        except (httpx.HTTPError, ValueError) as exc:
            info.update(reachable=False, error=str(exc)[:200])
    elif p == "anthropic":
        info.update(reachable=True, model=settings.ANTHROPIC_MODEL)
    return info
