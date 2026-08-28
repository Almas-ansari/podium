"""Tier 1 delivery metrics, computed from the transcript and word timestamps.

Everything here is deterministic. The same audio produces the same numbers on
every run. The LLM is never asked to judge any of this.
"""
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Optional

from .config import DATA_DIR

FILLERS = ("um", "uh", "er", "like", "so", "basically", "actually", "matlab", "yaani")

PAUSE_THRESHOLD = 0.7      # seconds; a gap above this is a hesitation
OPENING_WINDOW = 15.0      # seconds; pauses clustered here mean a weak opening
LONG_SILENCE = 3.0         # seconds; a gap this long reads as going blank

PACE_HESITANT = 90
PACE_LOW = 100
PACE_HIGH = 150
PACE_RUSHING = 170

_WORD_RE = re.compile(r"[a-z']+")

# Used only to stop "and the" style n-grams dominating the repetition report.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "is", "are", "was", "were", "it", "its", "this", "that", "i", "my", "we",
    "you", "he", "she", "they", "be", "am", "as", "with", "so", "then",
}


@lru_cache(maxsize=1)
def common_words() -> frozenset[str]:
    path = DATA_DIR / "top1000.txt"
    return frozenset(w.strip().lower() for w in path.read_text(encoding="utf-8").split() if w.strip())


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("’", "'"))


def _round(value: Optional[float], places: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), places)


# --- individual metrics ---------------------------------------------------

def pace(words: list[dict], transcript: str, audio_duration: float) -> dict[str, Any]:
    """Words per minute over the window the child was actually speaking in."""
    tokens = tokenize(transcript)
    n = len(tokens) or len(words)

    if len(words) >= 2:
        span = float(words[-1]["end"]) - float(words[0]["start"])
    else:
        span = float(audio_duration)
    span = max(span, 1e-6)

    wpm = n / span * 60.0

    if wpm < PACE_HESITANT:
        band = "hesitant"
    elif wpm > PACE_RUSHING:
        band = "rushing"
    elif PACE_LOW <= wpm <= PACE_HIGH:
        band = "typical"
    elif wpm < PACE_LOW:
        band = "slightly slow"
    else:
        band = "slightly fast"

    return {
        "wpm": _round(wpm, 1),
        "word_count": n,
        "speaking_span_s": _round(span, 2),
        "band": band,
        "flag": band if band in ("hesitant", "rushing") else None,
    }


def fillers(transcript: str, speaking_span: float) -> dict[str, Any]:
    """Whole-word, case-insensitive filler counts, raw and per minute."""
    tokens = tokenize(transcript)
    counts = Counter(t for t in tokens if t in FILLERS)
    total = sum(counts.values())
    minutes = max(speaking_span, 1e-6) / 60.0
    per_min = total / minutes

    most_common = counts.most_common(1)[0][0] if counts else None

    return {
        "total": total,
        "per_minute": _round(per_min, 1),
        "breakdown": dict(counts.most_common()),
        "most_common": most_common,
        # Whisper decoding sometimes drops disfluencies. A zero here is weak
        # evidence, not proof, so downstream feedback must not celebrate it.
        "reliable": total > 0,
        "heavy": per_min >= 6.0,
    }


def pauses(words: list[dict]) -> dict[str, Any]:
    """Gaps between adjacent words. Where they cluster is the useful part."""
    gaps: list[dict[str, float]] = []
    for a, b in zip(words, words[1:]):
        # Rounded before comparing: word timestamps arrive at 10 ms resolution,
        # and raw float subtraction turns a clean 0.70 gap into 0.7000000000000002,
        # which would classify identical pauses differently from one run to the next.
        gap = round(float(b["start"]) - float(a["end"]), 3)
        if gap > PAUSE_THRESHOLD:
            gaps.append({"at": _round(a["end"], 2), "length": _round(gap, 2)})

    if not words:
        return {
            "count": 0, "longest": 0.0, "in_first_15s": 0, "weak_opening": False,
            "went_blank": False, "pauses": [], "distribution": {},
        }

    start = float(words[0]["start"])
    end = float(words[-1]["end"])
    span = max(end - start, 1e-6)

    in_opening = sum(1 for g in gaps if g["at"] - start <= OPENING_WINDOW)
    thirds = {"first": 0, "middle": 0, "last": 0}
    for g in gaps:
        frac = (g["at"] - start) / span
        key = "first" if frac < 1 / 3 else ("middle" if frac < 2 / 3 else "last")
        thirds[key] += 1

    longest = max((g["length"] for g in gaps), default=0.0)

    return {
        "count": len(gaps),
        "longest": _round(longest, 2),
        "in_first_15s": in_opening,
        "weak_opening": in_opening >= 3,
        "went_blank": longest >= LONG_SILENCE,
        "distribution": thirds,
        "pauses": gaps[:40],
    }


def filler_positions(words: list[dict]) -> list[dict[str, Any]]:
    """Where each filler landed in time, for the session report timeline."""
    out = []
    for w in words:
        token = _WORD_RE.findall(w["word"].lower().replace("\u2019", "'"))
        if token and token[0] in FILLERS:
            out.append({"word": token[0], "at": round(float(w["start"]), 2)})
    return out


def repetition(transcript: str) -> dict[str, Any]:
    """Repeated bigrams and trigrams. This is literally how JAM is judged."""
    tokens = tokenize(transcript)

    def ngrams(n: int) -> Counter:
        grams = [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]
        return Counter(g for g in grams if not all(w in _STOPWORDS for w in g))

    bi = {" ".join(g): c for g, c in ngrams(2).most_common() if c >= 2}
    tri = {" ".join(g): c for g, c in ngrams(3).most_common() if c >= 2}

    repeated_tokens = sum((c - 1) * 2 for c in bi.values())
    rate = repeated_tokens / len(tokens) if tokens else 0.0

    return {
        "bigrams": dict(list(bi.items())[:8]),
        "trigrams": dict(list(tri.items())[:5]),
        "repeated_bigram_types": len(bi),
        "repeated_trigram_types": len(tri),
        "rate": _round(rate, 3),
        "heavy": len(tri) >= 3 or rate > 0.25,
    }


def vocabulary(transcript: str) -> dict[str, Any]:
    """Type-token ratio plus words outside the common-word list."""
    tokens = tokenize(transcript)
    if not tokens:
        return {"ttr": 0.0, "unique": 0, "total": 0, "rare_count": 0,
                "rare_rate": 0.0, "examples": []}

    common = common_words()
    unique = set(tokens)
    rare = [t for t in unique if t not in common and len(t) > 3]

    return {
        "ttr": _round(len(unique) / len(tokens), 3),
        "unique": len(unique),
        "total": len(tokens),
        "rare_count": len(rare),
        "rare_rate": _round(len(rare) / len(unique), 3),
        "examples": sorted(rare, key=len, reverse=True)[:8],
    }


def completion(words: list[dict], audio_duration: float, target_seconds: int) -> dict[str, Any]:
    """Did the child fill the time, or run out of things to say?

    Feeds the top item in the feedback priority order, so it is deliberately
    conservative: only clear cases are called "ran out".
    """
    spoken = float(words[-1]["end"]) if words else 0.0
    target = max(int(target_seconds), 1)
    ratio = spoken / target

    trailing_silence = max(float(audio_duration) - spoken, 0.0)

    return {
        "spoken_until_s": _round(spoken, 2),
        "target_seconds": target,
        "coverage": _round(min(ratio, 1.0), 3),
        "trailing_silence_s": _round(trailing_silence, 2),
        "ran_out": ratio < 0.6 or trailing_silence > 5.0,
        "went_full_distance": ratio >= 0.9,
    }


# --- entry point ----------------------------------------------------------

def compute(
    transcript: str,
    words: list[dict],
    audio_duration: float,
    target_seconds: int,
) -> dict[str, Any]:
    p = pace(words, transcript, audio_duration)
    span = p["speaking_span_s"] or max(audio_duration, 1e-6)
    return {
        "duration_s": _round(audio_duration, 2),
        "pace": p,
        "fillers": fillers(transcript, span),
        "pauses": pauses(words),
        "repetition": repetition(transcript),
        "vocabulary": vocabulary(transcript),
        "completion": completion(words, audio_duration, target_seconds),
        "has_word_timestamps": bool(words),
    }
