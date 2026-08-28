"""Idea quality scoring. The LLM sees the transcript; it never judges delivery.

Seven dimensions, 1-5, strict JSON. The two modes are weighted differently:
in a prepared speech, weak structure and thin development are preparation
failures worth naming. In an impromptu speech they are the normal cost of
thinking aloud and are weighted down accordingly.
"""
import json
import logging
import re
from typing import Any, Optional

from . import groq_client

log = logging.getLogger(__name__)

DIMENSIONS = (
    "specificity", "personal_stake", "reasoning", "angle",
    "development", "on_topic", "structure",
)

WEIGHTS = {
    "prepared": {
        "specificity": 1.0, "personal_stake": 0.8, "reasoning": 1.0, "angle": 0.8,
        "development": 1.0, "on_topic": 1.0, "structure": 1.0,
    },
    "impromptu": {
        "specificity": 1.0, "personal_stake": 1.0, "reasoning": 0.8, "angle": 0.8,
        "development": 0.5, "on_topic": 1.0, "structure": 0.4,
    },
}

SYSTEM = """You score the IDEAS in a child's short spoken speech. You are given a
transcript produced by automatic speech recognition, so expect missing punctuation,
odd word breaks and transcription errors. Judge the thinking, never the transcription.

You must NOT comment on voice, tone, pace, volume, confidence or nerves. You cannot
hear the audio. Those are measured separately.

Score each dimension 1 to 5 (1 = absent, 3 = present but ordinary, 5 = strong for a child of this age):
- specificity: concrete details, named people, places, numbers, moments, versus abstractions
- personal_stake: did the child put themselves in it, an experience or an opinion they own
- reasoning: claims backed with a reason ("because..."), versus asserted and dropped
- angle: their own way into the topic, versus the most obvious take
- development: one idea properly explored, versus several ideas touched and abandoned
- on_topic: did they stay with the topic they were given
- structure: a clear opening and a real ending, versus starting mid-thought and just stopping

Judge against what is realistic for the child's age band, not against an adult.

Return ONLY a JSON object, no prose and no markdown fences, with exactly these keys:
{
 "specificity": int, "personal_stake": int, "reasoning": int, "angle": int,
 "development": int, "on_topic": int, "structure": int,
 "has_opening": boolean,
 "has_ending": boolean,
 "distinct_points": int,
 "used_example": boolean,
 "main_idea": "one short phrase naming what the child actually said",
 "strongest_moment": "the single best specific thing the child said, quoted or closely paraphrased, max 20 words",
 "biggest_opening": "the one place where a concrete detail or a reason would have added the most, max 25 words"
}"""


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _clamp_score(value: Any) -> Optional[int]:
    try:
        return max(1, min(5, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def _normalise(parsed: dict) -> Optional[dict[str, Any]]:
    scores = {d: _clamp_score(parsed.get(d)) for d in DIMENSIONS}
    if any(v is None for v in scores.values()):
        return None

    def text(key: str, limit: int) -> str:
        val = parsed.get(key)
        return str(val).strip()[:limit] if isinstance(val, (str, int, float)) else ""

    try:
        points = max(0, min(10, int(float(parsed.get("distinct_points", 0)))))
    except (TypeError, ValueError):
        points = 0

    return {
        **scores,
        "has_opening": bool(parsed.get("has_opening")),
        "has_ending": bool(parsed.get("has_ending")),
        "distinct_points": points,
        "used_example": bool(parsed.get("used_example")),
        "main_idea": text("main_idea", 120),
        "strongest_moment": text("strongest_moment", 200),
        "biggest_opening": text("biggest_opening", 200),
    }


def weighted_score(scores: dict[str, Any], mode: str) -> dict[str, Any]:
    """Mode-aware overall. Parent dashboard only - never shown to the child."""
    weights = WEIGHTS.get(mode, WEIGHTS["impromptu"])
    total = sum(weights[d] * float(scores[d]) for d in DIMENSIONS)
    denom = sum(weights.values())
    out_of_5 = total / denom
    return {
        "out_of_5": round(out_of_5, 2),
        "out_of_100": int(round((out_of_5 - 1) / 4 * 100)),
        "mode_weighting": mode,
    }


def score(transcript: str, topic: str, mode: str, age_band: str) -> dict[str, Any]:
    """Returns {"available": bool, ...scores} - never raises to the caller."""
    if not transcript.strip():
        return {"available": False, "reason": "empty transcript"}

    user = (
        f"Child age band: {age_band}\n"
        f"Mode: {mode}\n"
        f"Topic given: \"{topic}\"\n"
        f"Transcript:\n\"\"\"\n{transcript.strip()}\n\"\"\"\n\n"
        "Return the JSON object now."
    )

    for attempt in (1, 2):  # malformed JSON gets exactly one retry
        try:
            raw = groq_client.chat_json(SYSTEM, user, max_tokens=1600)
        except Exception as exc:
            log.warning("idea scoring call failed (attempt %d): %s", attempt, exc)
            break

        parsed = _extract_json(raw)
        normalised = _normalise(parsed) if parsed else None
        if normalised:
            normalised["available"] = True
            normalised["overall"] = weighted_score(normalised, mode)
            return normalised

        log.warning("idea scoring returned unparseable JSON (attempt %d)", attempt)

    # Degrade to delivery-only feedback rather than inventing idea scores.
    return {"available": False, "reason": "idea scoring unavailable"}
