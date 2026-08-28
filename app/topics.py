"""Topic bank: load, filter by age band and mode, rotate without repeating."""
import json
import random
from functools import lru_cache
from typing import Any, Optional

from . import db
from .config import DATA_DIR

TOPICS_PATH = DATA_DIR / "topics.json"


@lru_cache(maxsize=1)
def all_topics() -> list[dict[str, Any]]:
    with TOPICS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=16)
def pool(age_band: str, mode: str) -> list[dict[str, Any]]:
    return [t for t in all_topics() if t["age_band"] == age_band and mode in t["modes"]]


def by_id(topic_id: int) -> Optional[dict[str, Any]]:
    for t in all_topics():
        if t["id"] == topic_id:
            return t
    return None


def pick(child_id: str, age_band: str, mode: str, exclude_id: Optional[int] = None) -> dict[str, Any]:
    """A topic this child has not had yet. When the pool is exhausted it resets.

    exclude_id lets the "different topic" button avoid handing back the same
    topic twice in a row.
    """
    candidates = pool(age_band, mode)
    if not candidates:  # should not happen, every band+mode pool is populated
        candidates = pool(age_band, "impromptu") or all_topics()

    used = db.used_topic_ids(child_id)
    fresh = [t for t in candidates if t["id"] not in used]

    if not fresh:
        db.reset_topic_history(child_id, [t["id"] for t in candidates])
        fresh = list(candidates)

    if exclude_id is not None and len(fresh) > 1:
        fresh = [t for t in fresh if t["id"] != exclude_id]

    return random.choice(fresh)


def band_stats(child_id: str, age_band: str, mode: str) -> tuple[int, int]:
    """(topics done in this band+mode, pool size) for the child-facing badge."""
    candidates = pool(age_band, mode)
    used = db.used_topic_ids(child_id)
    return sum(1 for t in candidates if t["id"] in used), len(candidates)


def showcase(count: int = 18) -> list[dict[str, Any]]:
    """A spread of real topics for the landing page.

    Drawn from the shipped bank rather than written for marketing, so what a
    visitor sees is what a child actually gets. Age bands are interleaved, or
    the strip reads as a wall of one band.
    """
    from .config import AGE_BANDS

    by_band: dict[str, list[dict[str, Any]]] = {band: [] for band in AGE_BANDS}
    seen: set[tuple[str, str]] = set()
    for topic in all_topics():
        key = (topic["age_band"], topic["category"])
        if key in seen or len(topic["text"]) > 46:
            continue
        seen.add(key)
        by_band.setdefault(topic["age_band"], []).append(topic)

    out: list[dict[str, Any]] = []
    for row in zip(*(by_band[band] for band in AGE_BANDS if by_band.get(band))):
        out.extend(row)
        if len(out) >= count:
            break
    return out[:count]
