"""Groq API access: Whisper transcription with word timestamps, and the LLM.

Both calls share one key and one SDK. Every call goes through _with_backoff,
because the free tier is 20 requests/minute and a class of ten children all
finishing at once will hit that.
"""
import logging
import random
import time
from typing import Any, Callable, Optional

from groq import APIConnectionError, APIStatusError, Groq, RateLimitError

from .config import (
    BASE_BACKOFF_SECONDS, GROQ_API_KEY, LLM_MODEL, LLM_REASONING_EFFORT,
    MAX_RETRIES, REASONING_MODEL_HINTS, WHISPER_MODEL,
)

log = logging.getLogger(__name__)

_client: Optional[Groq] = None


class TranscriptionError(RuntimeError):
    pass


def client() -> Groq:
    global _client
    if not GROQ_API_KEY:
        raise TranscriptionError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _retry_after(exc: Exception) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    for key in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-audio-seconds"):
        raw = headers.get(key)
        if not raw:
            continue
        try:
            return float(str(raw).rstrip("s"))
        except ValueError:
            continue
    return None


def _with_backoff(fn: Callable[[], Any], what: str) -> Any:
    delay = BASE_BACKOFF_SECONDS
    last: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except RateLimitError as exc:
            last = exc
            wait = _retry_after(exc) or delay
            # jitter so simultaneous finishers do not retry in lockstep
            wait = min(wait, 30.0) + random.uniform(0, 0.5)
            log.warning("%s rate limited (attempt %d), sleeping %.1fs", what, attempt + 1, wait)
            time.sleep(wait)
            delay *= 2
        except (APIConnectionError, APIStatusError) as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise  # a bad request will not get better by retrying
            last = exc
            log.warning("%s transient failure (attempt %d): %s", what, attempt + 1, exc)
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2
    raise TranscriptionError(f"{what} failed after {MAX_RETRIES} attempts: {last}")


def transcribe(audio_bytes: bytes, filename: str = "speech.wav") -> dict[str, Any]:
    """Returns {"text": str, "words": [{"word","start","end"}, ...], "duration": float}.

    Word-level timestamps are mandatory: every pause and pace metric is derived
    from them. If Groq returns none, the caller must know rather than silently
    scoring an empty list.
    """
    def call() -> Any:
        return client().audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language="en",
            temperature=0.0,
        )

    result = _with_backoff(call, "transcription")
    payload = result if isinstance(result, dict) else result.model_dump()

    words = []
    for w in payload.get("words") or []:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        try:
            words.append({"word": token, "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue

    return {
        "text": (payload.get("text") or "").strip(),
        "words": words,
        "duration": float(payload.get("duration") or 0.0),
        "segments": payload.get("segments") or [],
    }


def _is_reasoning_model(model: str) -> bool:
    lowered = model.lower()
    return any(hint in lowered for hint in REASONING_MODEL_HINTS)


def chat_json(system: str, user: str, max_tokens: int = 1400) -> str:
    """One LLM call constrained to a JSON object. Temperature 0 for stability."""
    kwargs: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    # Reasoning models bill their thinking against max_tokens, so keep the
    # thinking short: this is formatting work, not a puzzle.
    if LLM_REASONING_EFFORT and _is_reasoning_model(LLM_MODEL):
        kwargs["reasoning_effort"] = LLM_REASONING_EFFORT

    def call() -> Any:
        return client().chat.completions.create(**kwargs)

    completion = _with_backoff(call, "llm")
    return completion.choices[0].message.content or ""
