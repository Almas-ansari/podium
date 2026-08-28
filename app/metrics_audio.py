"""Tier 2 delivery metrics: RMS energy and pitch, computed locally.

No API calls and no audio leaves the machine. Raw values only; the meaning of
a pitch or volume number is decided later against the child's own baseline,
never against a fixed threshold (see baseline.py).
"""
import logging
import wave
from pathlib import Path
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)

FRAME_S = 0.05          # 50 ms analysis window for RMS
SILENCE_FLOOR_RATIO = 0.15   # fraction of median speech energy that counts as silence


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    """Reads a PCM WAV into mono float32 in [-1, 1]. stdlib only, no ffmpeg."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width: {width}")

    if channels > 1:
        usable = (len(data) // channels) * channels
        data = data[:usable].reshape(-1, channels).mean(axis=1)

    return data, rate


def _rms_frames(samples: np.ndarray, rate: int) -> np.ndarray:
    size = max(int(FRAME_S * rate), 1)
    usable = (len(samples) // size) * size
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[:usable].reshape(-1, size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def volume(samples: np.ndarray, rate: int) -> dict[str, Any]:
    """Overall energy, steadiness, and whether the child trails off at the end.

    Trailing off is extremely common in nervous children and is fixable with a
    single instruction, so it earns its own flag.
    """
    rms = _rms_frames(samples, rate)
    if rms.size == 0:
        return {"available": False}

    speech = rms[rms > rms.max() * SILENCE_FLOOR_RATIO] if rms.max() > 0 else rms
    if speech.size == 0:
        return {"available": False}

    mean_rms = float(speech.mean())
    # coefficient of variation: how uneven the loudness is, scale-free
    consistency = float(speech.std() / mean_rms) if mean_rms > 0 else 0.0

    third = max(speech.size // 3, 1)
    early = float(speech[: third * 2].mean())
    late = float(speech[third * 2:].mean()) if speech.size > third * 2 else early
    drop_pct = ((early - late) / early * 100.0) if early > 0 else 0.0

    return {
        "available": True,
        "mean_rms": round(mean_rms, 5),
        "variation": round(consistency, 3),
        "final_third_drop_pct": round(drop_pct, 1),
        "trails_off": drop_pct >= 25.0,
    }


def speech_ratio(samples: np.ndarray, rate: int) -> dict[str, Any]:
    """Proportion of the clip that carried speech rather than silence."""
    rms = _rms_frames(samples, rate)
    if rms.size == 0:
        return {"available": False}
    threshold = float(np.median(rms)) * 0.5 if float(rms.max()) > 0 else 0.0
    voiced = int(np.count_nonzero(rms > max(threshold, 1e-5)))
    return {
        "available": True,
        "ratio": round(voiced / rms.size, 3),
        "silence_ratio": round(1 - voiced / rms.size, 3),
    }


def envelope(samples: np.ndarray, rate: int, points: Optional[int] = None) -> list[float]:
    """A downsampled loudness curve for the session report.

    Stored with the session so the parent can see *where* the voice dropped,
    not just that it dropped on average. Normalised to its own peak, because
    the absolute level depends on how far the child sat from the microphone.
    """
    rms = _rms_frames(samples, rate)
    if rms.size == 0:
        return []
    peak = float(rms.max())
    if peak <= 0:
        return []

    if points is None:
        # About two buckets a second. Finer than this and the curve tracks
        # individual syllables, which reads as noise rather than shape.
        seconds = len(samples) / rate
        points = int(max(24, min(60, seconds * 2)))

    buckets = np.array_split(rms, min(points, rms.size))
    curve = np.array([float(b.mean()) / peak for b in buckets if b.size])

    # A five-point moving average on top. The useful signal is the overall
    # shape, especially whether the voice fades towards the end.
    if curve.size >= 5:
        padded = np.concatenate([curve[:2], curve, curve[-2:]])
        curve = np.convolve(padded, np.ones(5) / 5, mode="valid")

    return [round(float(v), 3) for v in curve]


def pitch(samples: np.ndarray, rate: int) -> dict[str, Any]:
    """F0 mean and standard deviation via Praat (parselmouth).

    The floor and ceiling are opened up well past adult defaults: a 7 year old
    routinely sits above the 600 Hz ceiling Praat uses out of the box.
    """
    try:
        import parselmouth
    except ImportError:  # pragma: no cover - dependency is in requirements.txt
        log.warning("parselmouth unavailable, skipping pitch")
        return {"available": False, "reason": "parselmouth not installed"}

    try:
        sound = parselmouth.Sound(samples.astype(np.float64), sampling_frequency=rate)
        track = sound.to_pitch(pitch_floor=75.0, pitch_ceiling=600.0)
        values = track.selected_array["frequency"]
        voiced = values[values > 0]
        if voiced.size < 10:
            return {"available": False, "reason": "too little voiced audio"}
        return {
            "available": True,
            "mean_hz": round(float(voiced.mean()), 1),
            "std_hz": round(float(voiced.std()), 1),
            "min_hz": round(float(voiced.min()), 1),
            "max_hz": round(float(voiced.max()), 1),
            "voiced_frames": int(voiced.size),
        }
    except Exception as exc:  # praat throws on very short or silent input
        log.warning("pitch analysis failed: %s", exc)
        return {"available": False, "reason": str(exc)[:120]}


def compute(audio_path: Path) -> dict[str, Any]:
    try:
        samples, rate = load_wav(Path(audio_path))
    except Exception as exc:
        log.warning("could not read audio %s: %s", audio_path, exc)
        return {"available": False, "reason": str(exc)[:160]}

    if samples.size == 0:
        return {"available": False, "reason": "empty audio"}

    return {
        "available": True,
        "sample_rate": rate,
        "duration_s": round(len(samples) / rate, 2),
        "volume": volume(samples, rate),
        "pitch": pitch(samples, rate),
        "speech": speech_ratio(samples, rate),
        "envelope": envelope(samples, rate),
    }
