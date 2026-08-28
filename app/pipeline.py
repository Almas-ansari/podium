"""One recording in, one stored session and one piece of feedback out."""
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from . import baseline, db, feedback, groq_client, ideas, metrics_audio, metrics_text
from .config import AUDIO_DIR

log = logging.getLogger(__name__)

MIN_WORDS = 5  # below this there is nothing to coach


class NoSpeechError(RuntimeError):
    """Raised when the recording contains no usable speech."""


def scratch_audio(child_id: str, audio_bytes: bytes) -> Path:
    """Writes the upload to disk only long enough to analyse it.

    parselmouth reads from a file, so the bytes have to land somewhere. The
    caller deletes it in a finally block: no recording of a child ever outlives
    the request that produced it. Playback copies live in the family's own
    browser instead (see static/audiostore.js).
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / f"tmp_{child_id}_{uuid.uuid4().hex}.wav"
    path.write_bytes(audio_bytes)
    return path


def process(
    child_id: str,
    age_band: str,
    mode: str,
    topic: dict[str, Any],
    target_seconds: int,
    audio_bytes: bytes,
) -> dict[str, Any]:
    audio_path = scratch_audio(child_id, audio_bytes)
    try:
        return _analyse(child_id, age_band, mode, topic, target_seconds,
                        audio_bytes, audio_path)
    finally:
        # Always, including on every error path.
        audio_path.unlink(missing_ok=True)


def _analyse(
    child_id: str,
    age_band: str,
    mode: str,
    topic: dict[str, Any],
    target_seconds: int,
    audio_bytes: bytes,
    audio_path: Path,
) -> dict[str, Any]:
    # 1. Transcript with word timestamps. Every Tier 1 metric depends on these.
    result = groq_client.transcribe(audio_bytes, filename=audio_path.name)
    transcript = result["text"]
    words = result["words"]

    if len(metrics_text.tokenize(transcript)) < MIN_WORDS:
        raise NoSpeechError("We could not hear enough speech in that recording.")

    # 2. Delivery, measured numerically. The LLM never touches this.
    audio_metrics = metrics_audio.compute(audio_path)
    duration = result["duration"] or audio_metrics.get("duration_s") or 0.0
    metrics = metrics_text.compute(transcript, words, duration, target_seconds)
    metrics["audio"] = audio_metrics

    # 3. Pitch and volume mean nothing until this child has their own baseline.
    history = db.metrics_history(child_id)
    base = baseline.build(history)
    norm = baseline.compare(audio_metrics, base)
    metrics["normalised"] = norm

    # 4. Ideas, from the transcript only. Degrades to delivery-only on failure.
    idea_scores = ideas.score(transcript, topic["text"], mode, age_band)

    # 5. Badges reflect the session about to be stored, so count it in.
    rows = db.list_sessions(child_id)
    done_topics, _ = _topic_progress(child_id, age_band, mode)
    badges = feedback.build_badges(
        sessions_done=len(rows) + 1,
        session_dates=[r["created_at"] for r in rows] + [db.now_iso()],
        topics_done=done_topics,
    )

    # 6. Numbers decide what to say; the LLM only writes the sentence.
    child_feedback = feedback.build(
        age_band=age_band, mode=mode, topic=topic["text"], transcript=transcript,
        metrics=metrics, ideas=idea_scores, norm=norm, badges=badges,
    )

    session_id = db.insert_session({
        "child_id": child_id,
        "created_at": db.now_iso(),
        "mode": mode,
        "age_band": age_band,
        "topic_id": topic.get("id"),
        "topic_text": topic["text"],
        "target_seconds": target_seconds,
        "duration": duration,
        "transcript": transcript,
        "words_json": json.dumps(words),
        "metrics_json": json.dumps(metrics),
        "ideas_json": json.dumps(idea_scores),
        "feedback_json": json.dumps(child_feedback),
        # Deliberately null: the server keeps transcripts and measurements, never audio.
        "audio_path": None,
    })

    if topic.get("id"):
        db.mark_topic_used(child_id, int(topic["id"]))

    return {
        "session_id": session_id,
        "feedback": child_feedback,
        "metrics": metrics,
        "ideas": idea_scores,
        "transcript": transcript,
    }


def _topic_progress(child_id: str, age_band: str, mode: str) -> tuple[int, int]:
    from . import topics
    done, total = topics.band_stats(child_id, age_band, mode)
    return done + 1, total
