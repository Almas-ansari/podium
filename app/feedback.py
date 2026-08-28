"""Child-facing feedback.

Three rules drive everything here:

1. The child never sees a number that could be read as a score. Ratings live in
   the database and on the parent dashboard only.
2. Exactly one thing to work on. Never two, never a list. A child given five
   corrections fixes none of them.
3. Idea feedback is additive, never evaluative. "Next time tell us about one
   Diwali you remember" carries the same information as "your point was
   generic" and has the opposite effect on whether the child speaks again.

The choice of what to praise and what to correct is made here, deterministically,
from the measured numbers. The LLM only writes the sentence.
"""
import json
import logging
from collections import Counter
from datetime import date, datetime
from typing import Any, Optional

from . import groq_client

log = logging.getLogger(__name__)

# Priority order for the single improvement note. First match wins.
FOCUS_ORDER = (
    "ran_out", "rushing", "fillers", "development",
    "specifics", "monotone", "trailing_volume", "structure", "repetition",
)

AGE_STYLE = {
    "6-8": (
        "READER: a 6 to 8 year old. HARD LIMITS: every sentence under 12 words. "
        "The whole praise must be one sentence. Only words a 7 year old uses daily. "
        "No words like 'described', 'clearly', 'value', 'appreciate', 'detail', 'structure'. "
        "Warm and playful. "
        "Example of the right register: 'You told us your teacher stayed back to help you. "
        "That is a real story, and real stories are the best bit.'"
    ),
    "9-11": (
        "READER: a 9 to 11 year old. HARD LIMITS: sentences under 20 words, praise at most two sentences. "
        "Plain, friendly and concrete. You may name a simple technique if you explain it in everyday words. "
        "Example of the right register: 'You gave us a real moment, your teacher staying back after class. "
        "That is what makes people listen.'"
    ),
    "12-14": (
        "READER: a 12 to 14 year old. HARD LIMITS: sentences under 22 words, praise at most two sentences. "
        "Respectful and direct. Never babyish, never gushing, no exclamation marks, no 'well done'. "
        "Treat them as a young speaker who wants to get better and can take a straight note. "
        "Example of the right register: 'The moment about your teacher staying back did the work here, "
        "because it was specific enough to picture.'"
    ),
}

# Fallback wording used when the LLM is unreachable. Deliberately plain but
# still specific and still additive.
# Which half of the coaching each note belongs to. The product judges both what
# the child says and how they say it, and the feedback screen labels which is which.
IDEA_WINS = {"said_something_good", "personal", "specific", "reasoning", "angle",
             "opening_and_ending", "used_example", "good_words"}
IDEA_FOCUSES = {"development", "specifics", "structure", "repetition", "keep_going"}

FOCUS_FALLBACK = {
    "ran_out": "Next time, keep one extra story ready so you can carry on to the end of the time.",
    "rushing": "Next time, slow down a little and take a breath at the end of each sentence.",
    "fillers": "Next time, when you feel an 'um' coming, pause silently instead. A quiet gap sounds calm.",
    "development": "Next time, pick your best idea and stay with it for longer instead of moving on.",
    "specifics": "Next time, add one real example from your own life so we can picture it.",
    "monotone": "Next time, let your voice go up on the part you care about most.",
    "trailing_volume": "Next time, keep your voice just as strong on the last sentence as the first.",
    "structure": "Next time, finish with one closing line that tells us you are done.",
    "repetition": "Next time, try saying your main point in a new way instead of repeating it.",
    "keep_going": "Next time, try a topic you have never spoken about before.",
}

FALLBACK_WIN = "You stood up, picked a topic and spoke about it. That is the hard part."


# --- deciding what to say -------------------------------------------------

def choose_focus(metrics: dict, ideas: dict, norm: dict, mode: str) -> tuple[str, dict[str, Any]]:
    """The single highest-impact thing to work on, by fixed priority order."""
    pace = metrics.get("pace", {})
    fillers = metrics.get("fillers", {})
    pauses = metrics.get("pauses", {})
    completion = metrics.get("completion", {})
    repetition = metrics.get("repetition", {})
    have_ideas = bool(ideas.get("available"))
    calibrating = bool(norm.get("calibrating"))

    # In impromptu mode thin development and loose structure are the normal
    # cost of thinking aloud, so the bar to flag them is higher.
    dev_limit = 3 if mode == "prepared" else 2

    candidates: dict[str, bool] = {
        "ran_out": bool(completion.get("ran_out")) or bool(pauses.get("went_blank")),
        "rushing": pace.get("band") == "rushing",
        "fillers": bool(fillers.get("heavy")) and bool(fillers.get("reliable")),
        "development": have_ideas and ideas.get("development", 5) <= dev_limit,
        "specifics": have_ideas and ideas.get("specificity", 5) <= 2,
        # Pitch and volume are only trustworthy once the child has a baseline.
        "monotone": (not calibrating) and norm.get("pitch", {}).get("status") == "monotone",
        "trailing_volume": (not calibrating) and bool(norm.get("volume", {}).get("trails_off")),
        "structure": have_ideas and (
            not ideas.get("has_ending", True)
            if mode == "prepared"
            else (not ideas.get("has_ending", True) and not ideas.get("has_opening", True))
        ),
        "repetition": bool(repetition.get("heavy")),
    }

    for key in FOCUS_ORDER:
        if candidates.get(key):
            return key, _focus_evidence(key, metrics, ideas, norm)

    return "keep_going", {}


def _focus_evidence(key: str, metrics: dict, ideas: dict, norm: dict) -> dict[str, Any]:
    """The measured fact behind the chosen focus, handed to the LLM as context."""
    if key == "ran_out":
        c = metrics.get("completion", {})
        return {"spoke_for_s": c.get("spoken_until_s"), "target_s": c.get("target_seconds"),
                "longest_pause_s": metrics.get("pauses", {}).get("longest")}
    if key == "rushing":
        return {"wpm": metrics.get("pace", {}).get("wpm")}
    if key == "fillers":
        f = metrics.get("fillers", {})
        return {"total": f.get("total"), "per_minute": f.get("per_minute"),
                "most_common": f.get("most_common")}
    if key == "development":
        return {"main_idea": ideas.get("main_idea"), "distinct_points": ideas.get("distinct_points")}
    if key == "specifics":
        return {"main_idea": ideas.get("main_idea"), "opening": ideas.get("biggest_opening")}
    if key == "monotone":
        return {"vs_baseline": norm.get("pitch", {}).get("ratio")}
    if key == "trailing_volume":
        return {"drop_pct": norm.get("volume", {}).get("final_third_drop_pct")}
    if key == "structure":
        return {"has_opening": ideas.get("has_opening"), "has_ending": ideas.get("has_ending")}
    if key == "repetition":
        r = metrics.get("repetition", {})
        top = next(iter(r.get("trigrams") or r.get("bigrams") or {}), None)
        return {"repeated_phrase": top}
    return {}


def choose_win(metrics: dict, ideas: dict, norm: dict, focus: str) -> tuple[str, dict[str, Any]]:
    """One specific, true thing the child did well. Never generic praise."""
    pace = metrics.get("pace", {})
    fillers = metrics.get("fillers", {})
    pauses = metrics.get("pauses", {})
    completion = metrics.get("completion", {})
    vocab = metrics.get("vocabulary", {})
    have_ideas = bool(ideas.get("available"))
    calibrating = bool(norm.get("calibrating"))

    options: list[tuple[str, dict[str, Any]]] = []

    # Quoting something they actually said is the most specific praise available.
    if have_ideas and ideas.get("strongest_moment"):
        options.append(("said_something_good", {"moment": ideas["strongest_moment"]}))

    if completion.get("went_full_distance"):
        options.append(("full_distance", {"seconds": completion.get("target_seconds")}))

    if have_ideas:
        if ideas.get("personal_stake", 0) >= 4:
            options.append(("personal", {"main_idea": ideas.get("main_idea")}))
        if ideas.get("specificity", 0) >= 4:
            options.append(("specific", {"main_idea": ideas.get("main_idea")}))
        if ideas.get("reasoning", 0) >= 4:
            options.append(("reasoning", {}))
        if ideas.get("angle", 0) >= 4:
            options.append(("angle", {"main_idea": ideas.get("main_idea")}))
        if ideas.get("has_opening") and ideas.get("has_ending"):
            options.append(("opening_and_ending", {}))
        if ideas.get("used_example"):
            options.append(("used_example", {}))

    if pauses.get("count", 0) == 0 and metrics.get("has_word_timestamps"):
        options.append(("no_hesitation", {}))
    elif pauses.get("in_first_15s", 0) == 0 and metrics.get("has_word_timestamps"):
        options.append(("strong_start", {}))

    if pace.get("band") == "typical":
        options.append(("steady_pace", {"wpm": pace.get("wpm")}))

    # A zero filler count may just mean the transcriber dropped them, so only
    # praise fillers when some were actually detected and the rate is low.
    if fillers.get("reliable") and (fillers.get("per_minute") or 99) <= 2.0:
        options.append(("few_fillers", {}))

    if not calibrating and norm.get("pitch", {}).get("status") == "expressive":
        options.append(("expressive", {}))

    if vocab.get("rare_count", 0) >= 5 and vocab.get("examples"):
        options.append(("good_words", {"examples": vocab["examples"][:3]}))

    # Never praise the very thing being corrected.
    conflict = {
        "rushing": {"steady_pace"}, "fillers": {"few_fillers"},
        "ran_out": {"full_distance", "no_hesitation"},
        "monotone": {"expressive"}, "specifics": {"specific", "used_example"},
        "structure": {"opening_and_ending"},
        "development": {"reasoning"},
    }.get(focus, set())
    options = [o for o in options if o[0] not in conflict] or options

    return options[0] if options else ("showed_up", {})


# --- badges ---------------------------------------------------------------

def build_badges(sessions_done: int, session_dates: list[str], topics_done: int) -> dict[str, Any]:
    days = sorted({d[:10] for d in session_dates if d})
    streak = 0
    if days:
        cursor = date.fromisoformat(days[-1])
        for day in reversed(days):
            if (cursor - date.fromisoformat(day)).days == streak:
                streak += 1
                continue
            break

    labels = []
    if sessions_done == 1:
        labels.append("First speech done")
    elif sessions_done in (5, 10, 25, 50, 100):
        labels.append(f"{sessions_done} speeches")
    if streak >= 2:
        labels.append(f"{streak} days in a row")
    if topics_done >= 10:
        labels.append(f"{topics_done} topics explored")

    return {
        "sessions": sessions_done,
        "streak_days": streak,
        "topics": topics_done,
        "labels": labels,
    }


# --- the metric block handed to the LLM -----------------------------------

def metric_block(age_band: str, mode: str, topic: str, transcript: str,
                 metrics: dict, ideas: dict, norm: dict) -> str:
    pace = metrics.get("pace", {})
    fillers = metrics.get("fillers", {})
    pauses = metrics.get("pauses", {})
    completion = metrics.get("completion", {})

    lines = [
        f"Child age band: {age_band}",
        f"Mode: {mode}",
        f'Topic: "{topic}"',
        f"Transcript: \"{transcript.strip()}\"",
        f"Duration: {metrics.get('duration_s')}s (target {completion.get('target_seconds')}s)",
        f"Pace: {pace.get('wpm')} wpm ({pace.get('band')})",
    ]

    if fillers.get("reliable"):
        lines.append(
            f"Fillers: {fillers.get('total')}, mostly \"{fillers.get('most_common')}\" "
            f"({fillers.get('per_minute')}/min)"
        )
    else:
        lines.append("Fillers: none detected (the transcriber may have dropped them - do not praise this)")

    lines.append(
        f"Pauses over 0.7s: {pauses.get('count')}, {pauses.get('in_first_15s')} in the first 15 seconds, "
        f"longest {pauses.get('longest')}s"
    )
    lines.extend(baseline_lines(norm))

    if ideas.get("available"):
        lines.append(
            "Ideas (1-5): specificity {specificity}, personal stake {personal_stake}, "
            "reasoning {reasoning}, angle {angle}, development {development}, "
            "on topic {on_topic}, structure {structure}".format(**ideas)
        )
        if ideas.get("main_idea"):
            lines.append(f"What they actually said: {ideas['main_idea']}")
        if ideas.get("strongest_moment"):
            lines.append(f"Strongest moment: {ideas['strongest_moment']}")
        if ideas.get("biggest_opening"):
            lines.append(f"Biggest missed opportunity: {ideas['biggest_opening']}")
    else:
        lines.append("Ideas: not scored for this session - comment only on delivery")

    return "\n".join(lines)


def baseline_lines(norm: dict) -> list[str]:
    from .baseline import summarise_for_prompt
    return summarise_for_prompt(norm)


# --- LLM phrasing ---------------------------------------------------------

SYSTEM = """You write two sentences of spoken-word coaching for a child. You are warm,
specific and honest. You are not a cheerleader.

Absolute rules:
- NEVER give a score, mark, rating, percentage, grade or any "out of" number. Not even
  a hint of one. A child who sees a score stops speaking. Durations and counts of real
  things are fine.
- The praise must be about something the child actually did, taken from the data you are
  given. Never "great job", "well done", "amazing effort" on its own.
- Exactly ONE thing to try next time. Never two. Never a list.
- Phrase the improvement as an addition, not a verdict. Say what to add or try next time,
  never what was weak, generic, boring or missing.
- Do not mention transcripts, models, metrics, numbers of pauses, or that anything was measured.
- Speak directly to the child as "you".
- Use British spelling (favourite, colour, practise, realise).
- End every sentence with a full stop.

Return ONLY a JSON object, no prose, no markdown fences:
{"win": "one or two sentences", "tip": "one sentence starting with 'Next time,'"}"""


def _write_lines(age_band: str, mode: str, block: str, focus: str, focus_evidence: dict,
                 win: str, win_evidence: dict) -> Optional[dict[str, str]]:
    style = AGE_STYLE.get(age_band, AGE_STYLE["9-11"])
    user = (
        f"{block}\n\n"
        f"STYLE: {style}\n\n"
        f"The one thing to praise has already been chosen for you: {win}\n"
        f"Supporting detail: {json.dumps(win_evidence, ensure_ascii=False)}\n\n"
        f"The one thing to improve has already been chosen for you: {focus}\n"
        f"Supporting detail: {json.dumps(focus_evidence, ensure_ascii=False)}\n\n"
        "Write the praise about that chosen strength only, and the tip about that chosen "
        "improvement only. Do not add a second tip.\n\n"
        f"Obey the STYLE limits exactly - they matter more than sounding polished: {style}\n"
        "Return the JSON now."
    )

    try:
        raw = groq_client.chat_json(SYSTEM, user, max_tokens=1200)
    except Exception as exc:
        log.warning("feedback phrasing failed: %s", exc)
        return None

    from .ideas import _extract_json
    parsed = _extract_json(raw)
    if not parsed:
        return None

    win_text = str(parsed.get("win", "")).strip()
    tip_text = str(parsed.get("tip", "")).strip()
    if not win_text or not tip_text:
        return None

    return {"win": _punctuate(win_text[:400]), "tip": _punctuate(tip_text[:300])}


def _punctuate(text: str) -> str:
    """Small models sometimes drop the final full stop. A child sees the line raw."""
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _fallback_win(win: str, evidence: dict, metrics: dict) -> str:
    completion = metrics.get("completion", {})
    texts = {
        "said_something_good": f"You said something worth hearing: {evidence.get('moment')}",
        "full_distance": f"You spoke for the whole {completion.get('target_seconds')} seconds without stopping.",
        "personal": "You put yourself into this one and told us what you actually think.",
        "specific": "You gave us real details, not just general words.",
        "reasoning": "You did not just say what you think, you told us why.",
        "angle": "You found your own way into this topic instead of the obvious one.",
        "opening_and_ending": "You opened properly and you finished properly.",
        "used_example": "You used a real example, and that is what makes a speech stick.",
        "no_hesitation": "You kept going the whole way through without getting stuck.",
        "strong_start": "You started straight away, with no hesitation at the beginning.",
        "steady_pace": "You spoke at a steady, easy speed the whole way through.",
        "few_fillers": "You kept your words clean, hardly any 'um' or 'uh'.",
        "expressive": "Your voice moved around today instead of staying flat.",
        "good_words": f"You used some strong words: {', '.join(evidence.get('examples', []) or [])}.",
        "showed_up": FALLBACK_WIN,
    }
    return texts.get(win, FALLBACK_WIN)


# --- entry point ----------------------------------------------------------

def build(age_band: str, mode: str, topic: str, transcript: str, metrics: dict,
          ideas: dict, norm: dict, badges: dict) -> dict[str, Any]:
    focus, focus_evidence = choose_focus(metrics, ideas, norm, mode)
    win, win_evidence = choose_win(metrics, ideas, norm, focus)

    block = metric_block(age_band, mode, topic, transcript, metrics, ideas, norm)
    written = _write_lines(age_band, mode, block, focus, focus_evidence, win, win_evidence)

    if written is None:
        written = {
            "win": _fallback_win(win, win_evidence, metrics),
            "tip": FOCUS_FALLBACK.get(focus, FOCUS_FALLBACK["keep_going"]),
        }
        source = "fallback"
    else:
        source = "llm"

    return {
        "win": written["win"],
        "tip": written["tip"],
        "win_half": "thinking" if win in IDEA_WINS else "speaking",
        "tip_half": "thinking" if focus in IDEA_FOCUSES else "speaking",
        "badges": badges,
        "focus_key": focus,
        "win_key": win,
        "source": source,
        "ideas_available": bool(ideas.get("available")),
        "calibrating": bool(norm.get("calibrating")),
    }


# --- parent-facing summary -------------------------------------------------

FOCUS_LABELS = {
    "ran_out": "running out of content",
    "rushing": "speaking too fast",
    "fillers": "filler words",
    "development": "developing one idea",
    "specifics": "giving concrete examples",
    "monotone": "vocal variety",
    "trailing_volume": "fading at the end",
    "structure": "opening and closing",
    "repetition": "repeating phrases",
    "keep_going": "nothing major",
}


def headline(history: list[dict]) -> dict[str, Any]:
    """A plain-English read on the trend, computed not written.

    history: [{"metrics": {...}, "ideas": {...}, "feedback": {...}}, ...] oldest first.
    Parents do not want to interpret four line charts; they want to know whether
    this is working.
    """
    if len(history) < 2:
        return {
            "text": "One more speech and trends start appearing here.",
            "tone": "neutral",
            "detail": None,
        }

    def series(path: tuple[str, ...]) -> list[float]:
        out = []
        for h in history:
            node: Any = h.get("metrics", {})
            for key in path:
                node = node.get(key, {}) if isinstance(node, dict) else None
            if isinstance(node, (int, float)):
                out.append(float(node))
        return out

    half = max(len(history) // 2, 1)

    def shift(values: list[float]) -> Optional[float]:
        if len(values) < 2:
            return None
        early = sum(values[:half]) / len(values[:half])
        late = sum(values[half:]) / max(len(values[half:]), 1)
        return late - early

    fillers = series(("fillers", "per_minute"))
    pace = series(("pace", "wpm"))
    pauses = series(("pauses", "count"))

    filler_shift = shift(fillers)
    pause_shift = shift(pauses)

    # In-band pace matters more than pace direction: 168 -> 150 is progress,
    # 130 -> 150 is not.
    def out_of_band(wpm: float) -> float:
        return 0.0 if 100 <= wpm <= 150 else min(abs(wpm - 100), abs(wpm - 150))

    pace_shift = shift([out_of_band(v) for v in pace]) if pace else None

    wins = []
    if filler_shift is not None and filler_shift <= -1.0:
        wins.append(("fillers", f"filler words are down {abs(filler_shift):.1f} a minute"))
    if pace_shift is not None and pace_shift <= -8:
        wins.append(("pace", "pace has moved towards a comfortable speed"))
    if pause_shift is not None and pause_shift <= -1.0:
        wins.append(("pauses", "there are fewer long hesitations"))

    slips = []
    if filler_shift is not None and filler_shift >= 1.5:
        slips.append(f"filler words are up {filler_shift:.1f} a minute")
    if pace_shift is not None and pace_shift >= 10:
        slips.append("pace has drifted further from a comfortable speed")

    counts = Counter(
        h.get("feedback", {}).get("focus_key")
        for h in history
        if h.get("feedback", {}).get("focus_key")
    )
    common = counts.most_common(1)[0] if counts else None
    detail = None
    if common and common[1] >= 2:
        detail = (
            f"{FOCUS_LABELS.get(common[0], common[0])} has come up in "
            f"{common[1]} of {len(history)} speeches"
        )

    if wins:
        text = "Across these speeches, " + " and ".join(w[1] for w in wins[:2]) + "."
        tone = "good"
    elif slips:
        text = "Across these speeches, " + " and ".join(slips[:2]) + "."
        tone = "watch"
    else:
        text = "Delivery has held steady across these speeches."
        tone = "neutral"

    return {"text": text, "tone": tone, "detail": detail}


def session_summary(metrics: dict, ideas: dict, norm: dict, mode: str) -> dict[str, Any]:
    """A plain-English read on one speech, assembled from the measured numbers.

    Sits at the top of the report so a parent gets the gist before deciding
    whether to read nine metric tiles. Deterministic: same session, same words.
    """
    pace = metrics.get("pace", {})
    fillers = metrics.get("fillers", {})
    pauses = metrics.get("pauses", {})
    completion = metrics.get("completion", {})

    parts: list[str] = []

    spoken = completion.get("spoken_until_s")
    target = completion.get("target_seconds")
    if spoken and target:
        if completion.get("went_full_distance"):
            parts.append(f"Spoke for the full {int(target)} seconds")
        else:
            parts.append(f"Spoke for {int(spoken)} of {int(target)} seconds")

    wpm, band = pace.get("wpm"), pace.get("band")
    if wpm:
        wording = {"rushing": "rushing", "hesitant": "hesitant",
                   "typical": "a comfortable speed", "slightly fast": "slightly fast",
                   "slightly slow": "slightly slow"}.get(band, band)
        parts.append(f"at {wpm:.0f} words a minute, {wording}")

    delivery = ". ".join([" ".join(parts)]) if parts else ""

    detail: list[str] = []
    if fillers.get("reliable") and fillers.get("total"):
        most = fillers.get("most_common")
        detail.append(
            f"{fillers['total']} filler word{'s' if fillers['total'] != 1 else ''}"
            + (f", mostly \"{most}\"" if most else "")
        )
    count = pauses.get("count", 0)
    if count:
        where = f", {pauses['in_first_15s']} in the opening" if pauses.get("in_first_15s") else ""
        detail.append(f"{count} long pause{'s' if count != 1 else ''}{where}")
    if not norm.get("calibrating") and norm.get("volume", {}).get("trails_off"):
        detail.append("the voice fades towards the end")

    thinking = ""
    if ideas.get("available"):
        bits = []
        bits.append("stayed on topic" if ideas.get("on_topic", 0) >= 4 else "drifted off topic")
        points = ideas.get("distinct_points", 0)
        if points:
            bits.append(f"made {points} distinct point{'s' if points != 1 else ''}")
        bits.append("used a real example" if ideas.get("used_example") else "used no concrete example")
        if not ideas.get("has_ending"):
            bits.append("stopped without a closing line")
        thinking = ", ".join(bits).capitalize() + "."

    return {
        "delivery": (delivery + ".") if delivery else "",
        "detail": ("; ".join(detail).capitalize() + ".") if detail else "",
        "thinking": thinking,
        "mode": mode,
    }
