"""Per-child normalisation for pitch and volume.

A 7 year old's fundamental frequency sits far above a 13 year old's. Judging
either against a fixed threshold would tell every young child they are
shrieking. So each child's own first three sessions become their baseline, and
until those exist these two metrics are reported as calibrating and generate no
feedback at all.
"""
from statistics import mean
from typing import Any, Optional

from .config import BASELINE_SESSIONS

# How far from baseline counts as a real change rather than session noise.
MONOTONE_RATIO = 0.7     # pitch variation at or below 70% of baseline
EXPRESSIVE_RATIO = 1.3
QUIET_RATIO = 0.7        # mean volume at or below 70% of baseline
LOUD_RATIO = 1.4


def _values(history: list[dict], *path: str) -> list[float]:
    out = []
    for entry in history:
        node: Any = entry
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, (int, float)) and node > 0:
            out.append(float(node))
    return out


def build(history: list[dict]) -> dict[str, Any]:
    """history: raw metrics dicts of this child's past sessions, oldest first."""
    pitch_std = _values(history, "audio", "pitch", "std_hz")[:BASELINE_SESSIONS]
    pitch_mean = _values(history, "audio", "pitch", "mean_hz")[:BASELINE_SESSIONS]
    vol_mean = _values(history, "audio", "volume", "mean_rms")[:BASELINE_SESSIONS]

    ready = (
        len(pitch_std) >= BASELINE_SESSIONS
        and len(vol_mean) >= BASELINE_SESSIONS
    )

    return {
        "ready": ready,
        "sessions_used": min(len(pitch_std), len(vol_mean)),
        "sessions_needed": BASELINE_SESSIONS,
        "pitch_std_hz": mean(pitch_std) if pitch_std else None,
        "pitch_mean_hz": mean(pitch_mean) if pitch_mean else None,
        "volume_rms": mean(vol_mean) if vol_mean else None,
    }


def compare(audio_metrics: dict, base: dict) -> dict[str, Any]:
    """Turns this session's raw pitch/volume into deviation from the child's own norm."""
    result: dict[str, Any] = {
        "calibrating": not base.get("ready"),
        "sessions_used": base.get("sessions_used", 0),
        "sessions_needed": base.get("sessions_needed", BASELINE_SESSIONS),
        "pitch": {"status": "calibrating", "ratio": None},
        "volume": {"status": "calibrating", "ratio": None},
    }

    if not audio_metrics.get("available"):
        result["pitch"]["status"] = "unavailable"
        result["volume"]["status"] = "unavailable"
        return result

    if not base.get("ready"):
        # Deliberately no verdict yet. Callers must not generate feedback here.
        return result

    pitch = audio_metrics.get("pitch") or {}
    vol = audio_metrics.get("volume") or {}

    base_pitch = base.get("pitch_std_hz")
    if pitch.get("available") and base_pitch:
        ratio = float(pitch["std_hz"]) / base_pitch
        if ratio <= MONOTONE_RATIO:
            status = "monotone"
        elif ratio >= EXPRESSIVE_RATIO:
            status = "expressive"
        else:
            status = "typical"
        result["pitch"] = {"status": status, "ratio": round(ratio, 2)}
    else:
        result["pitch"] = {"status": "unavailable", "ratio": None}

    base_vol = base.get("volume_rms")
    if vol.get("available") and base_vol:
        ratio = float(vol["mean_rms"]) / base_vol
        if ratio <= QUIET_RATIO:
            status = "quieter"
        elif ratio >= LOUD_RATIO:
            status = "louder"
        else:
            status = "typical"
        result["volume"] = {
            "status": status,
            "ratio": round(ratio, 2),
            "trails_off": bool(vol.get("trails_off")),
            "final_third_drop_pct": vol.get("final_third_drop_pct"),
        }
    else:
        result["volume"] = {"status": "unavailable", "ratio": None}

    return result


def summarise_for_prompt(norm: dict) -> list[str]:
    """Only lines the LLM is allowed to see. Calibrating metrics are withheld."""
    if norm.get("calibrating"):
        used, need = norm.get("sessions_used", 0), norm.get("sessions_needed", 3)
        return [f"Pitch and volume: still calibrating ({used}/{need} sessions) - do not comment on these"]

    lines = []
    pitch = norm.get("pitch", {})
    if pitch.get("status") in ("monotone", "expressive", "typical"):
        label = {"monotone": "low (flat) vs this child's baseline",
                 "expressive": "high (lively) vs this child's baseline",
                 "typical": "normal for this child"}[pitch["status"]]
        lines.append(f"Pitch variation: {label}")

    vol = norm.get("volume", {})
    if vol.get("status") in ("quieter", "louder", "typical"):
        label = {"quieter": "quieter than this child's usual",
                 "louder": "louder than this child's usual",
                 "typical": "normal for this child"}[vol["status"]]
        lines.append(f"Volume: {label}")
        if vol.get("trails_off"):
            lines.append(f"Volume drops {vol.get('final_third_drop_pct')}% in the final third")
    return lines
