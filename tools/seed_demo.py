"""Seeds demo sessions so the screens can be checked without spending API calls.

Runs the real metric code on real synthesised audio; only the transcript, word
timings and idea scores are canned. Feedback goes through the genuine fallback
path when no API key is configured.
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import baseline, db, feedback, metrics_audio, metrics_text  # noqa: E402
from app.config import AUDIO_DIR  # noqa: E402

CHILD = sys.argv[1] if len(sys.argv) > 1 else "demo0000000000000000000000000000"

SCRIPTS = [
    ("The best thing about my school", 90, "prepared",
     "um so the best thing about my school is the teachers uh they are really kind and they help "
     "us a lot like when i did not understand maths my teacher stayed back after class and "
     "explained it again and um also the library is very good we get to read many books and "
     "there is a big playground where we play cricket every day so that is the best thing about "
     "my school thank you", 3.1),
    ("Why we should not waste water", 90, "impromptu",
     "water is very important for everyone we should not waste water because uh many people in "
     "our country do not get clean water and like my grandmother tells me that in her village "
     "they walked two kilometres for water so we should close the tap while brushing and fix "
     "leaking taps at home that is what i think", 3.4),
    ("My favourite festival", 90, "prepared",
     "my favourite festival is diwali because the whole family comes together we clean the house "
     "and make rangoli in front of the door my grandmother makes ladoos and we light diyas in "
     "the evening last diwali my cousin came from pune and we lit sparklers together it was the "
     "happiest day so diwali is my favourite festival", 3.6),
    ("Should children have mobile phones", 90, "impromptu",
     "i think children should have mobile phones but only for some time because phones help us "
     "learn things and call our parents when we are late but um if we use it too much we stop "
     "playing outside and our eyes hurt so i think one hour a day is enough that is my opinion "
     "thank you", 3.0),
]


def synth(path: Path, seconds: float, base_hz: float, vibrato: float, fade: bool) -> None:
    sr = 16000
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    f0 = base_hz + vibrato * np.sin(2 * np.pi * 0.8 * t)
    sig = 0.28 * np.sin(2 * np.pi * np.cumsum(f0) / sr)
    sig *= 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 1.7 * t))  # syllable envelope
    if fade:
        tail = int(len(sig) * 0.3)
        sig[-tail:] *= np.linspace(1.0, 0.45, tail)
    for start in (0.32, 0.61):
        a = int(len(sig) * start)
        sig[a:a + int(sr * 0.9)] = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((sig * 32767).astype("<i2").tobytes())


def fake_words(transcript: str, wpm: float) -> list[dict]:
    tokens = metrics_text.tokenize(transcript)
    step = 60.0 / wpm
    words, clock = [], 0.6
    for i, tok in enumerate(tokens):
        if i and i % 23 == 0:
            clock += 1.1          # a hesitation pause
        words.append({"word": tok, "start": round(clock, 3), "end": round(clock + step * 0.75, 3)})
        clock += step
    return words


def main() -> None:
    db.init_db()
    db.ensure_child(CHILD, "9-11")
    db.record_consent(CHILD, "Almas Ansari")

    for n, (topic, target, mode, transcript, words_per_sec) in enumerate(SCRIPTS, start=1):
        wpm = words_per_sec * 60
        words = fake_words(transcript, wpm)
        duration = words[-1]["end"] + 1.2

        audio_path = AUDIO_DIR / f"{CHILD}_demo{n}.wav"
        synth(audio_path, duration, base_hz=250 - n * 6, vibrato=28 if n != 2 else 6, fade=(n == 2))

        audio = metrics_audio.compute(audio_path)
        metrics = metrics_text.compute(transcript, words, duration, target)
        metrics["audio"] = audio

        history = db.metrics_history(CHILD)
        base = baseline.build(history)
        norm = baseline.compare(audio, base)
        metrics["normalised"] = norm

        ideas = {
            "available": True, "specificity": 2 + (n % 3), "personal_stake": 4,
            "reasoning": 2 + (n % 2), "angle": 3, "development": 2 + (n % 2),
            "on_topic": 5, "structure": 3 if mode == "prepared" else 2,
            "has_opening": True, "has_ending": n != 2, "distinct_points": 2 + n % 3,
            "used_example": n in (1, 3),
            "main_idea": "what they liked and why",
            "strongest_moment": "my teacher stayed back after class and explained it again",
            "biggest_opening": "name the day it happened",
        }
        from app.ideas import weighted_score
        ideas["overall"] = weighted_score(ideas, mode)

        rows = db.list_sessions(CHILD)
        badges = feedback.build_badges(len(rows) + 1,
                                       [r["created_at"] for r in rows] + [db.now_iso()], n)
        fb = feedback.build("9-11", mode, topic, transcript, metrics, ideas, norm, badges)

        sid = db.insert_session({
            "child_id": CHILD, "created_at": db.now_iso(), "mode": mode, "age_band": "9-11",
            "topic_id": 100 + n, "topic_text": topic, "target_seconds": target,
            "duration": duration, "transcript": transcript, "words_json": json.dumps(words),
            "metrics_json": json.dumps(metrics), "ideas_json": json.dumps(ideas),
            "feedback_json": json.dumps(fb), "audio_path": str(audio_path),
        })
        print(f"#{n} session {sid} | pace {metrics['pace']['wpm']} wpm | "
              f"pauses {metrics['pauses']['count']} | focus={fb['focus_key']} ({fb['tip_half']}) | "
              f"win={fb['win_key']} ({fb['win_half']}) | calibrating={norm['calibrating']} | {fb['source']}")


if __name__ == "__main__":
    main()
