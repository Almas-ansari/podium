"""Unit tests for the deterministic half of the coach.

Nothing here touches the network. These are the numbers a parent is shown and
that decide what the child is told, so they are tested against hand-built
fixtures with known answers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import baseline, feedback, ideas, metrics_text  # noqa: E402


def words(spec):
    """spec: list of (word, start, end)."""
    return [{"word": w, "start": s, "end": e} for w, s, e in spec]


# --- pause detector -------------------------------------------------------

def test_pause_detects_only_gaps_over_threshold():
    w = words([
        ("one", 0.0, 0.4),
        ("two", 0.5, 0.9),    # gap 0.10 - not a pause
        ("three", 1.6, 2.0),  # gap 0.70 - exactly the threshold, excluded
        ("four", 2.9, 3.3),   # gap 0.90 - a pause
    ])
    result = metrics_text.pauses(w)
    assert result["count"] == 1
    assert result["longest"] == 0.9


def test_pause_threshold_is_exclusive_at_exactly_0_7():
    w = words([("a", 0.0, 1.0), ("b", 1.7, 2.0)])
    assert metrics_text.pauses(w)["count"] == 0
    w2 = words([("a", 0.0, 1.0), ("b", 1.71, 2.0)])
    assert metrics_text.pauses(w2)["count"] == 1


def test_pause_clustering_flags_a_weak_opening():
    spec, clock = [], 0.0
    for i in range(4):          # four long pauses inside the first 15 seconds
        spec.append((f"w{i}", clock, clock + 0.3))
        clock += 0.3 + 1.2
    for i in range(20):         # then fluent speech
        spec.append((f"x{i}", clock, clock + 0.3))
        clock += 0.35
    result = metrics_text.pauses(words(spec))
    assert result["in_first_15s"] >= 3
    assert result["weak_opening"] is True
    assert result["distribution"]["first"] > result["distribution"]["last"]


def test_pause_flags_going_blank_on_a_long_silence():
    w = words([("a", 0.0, 0.5), ("b", 4.0, 4.5)])
    assert metrics_text.pauses(w)["went_blank"] is True


def test_pause_handles_empty_word_list():
    result = metrics_text.pauses([])
    assert result["count"] == 0 and result["went_blank"] is False


# --- pace ------------------------------------------------------------------

def test_pace_uses_the_speaking_span_not_the_clip_length():
    # 60 words spoken between t=10 and t=40 is 120 wpm, even in a 90s clip.
    spec = [(f"w{i}", 10.0 + i * 0.5, 10.0 + i * 0.5 + 0.4) for i in range(60)]
    w = words(spec)
    result = metrics_text.pace(w, " ".join(x[0] for x in spec), audio_duration=90.0)
    assert 118 <= result["wpm"] <= 126
    assert result["band"] == "typical"


def test_pace_bands():
    def band(wpm):
        n = 100
        step = 60.0 / wpm
        spec = [(f"w{i}", i * step, i * step + step * 0.5) for i in range(n)]
        return metrics_text.pace(words(spec), " ".join(x[0] for x in spec), 60.0)["band"]

    assert band(70) == "hesitant"
    assert band(130) == "typical"
    assert band(200) == "rushing"


# --- fillers ---------------------------------------------------------------

def test_fillers_are_whole_word_and_case_insensitive():
    text = "Um I Like the umbrella so basically Actually it is likeable"
    result = metrics_text.fillers(text, speaking_span=60.0)
    # "umbrella" and "likeable" must not count
    assert result["breakdown"] == {"um": 1, "like": 1, "so": 1, "basically": 1, "actually": 1}
    assert result["total"] == 5
    assert result["per_minute"] == 5.0


def test_filler_rate_is_flagged_heavy_and_marked_unreliable_when_absent():
    heavy = metrics_text.fillers("um um um um um um um", speaking_span=60.0)
    assert heavy["heavy"] is True and heavy["reliable"] is True

    none = metrics_text.fillers("a clean sentence with no disfluency", speaking_span=60.0)
    # A zero may just mean the transcriber dropped them, so it is not evidence.
    assert none["total"] == 0 and none["reliable"] is False


def test_hindi_english_fillers_are_counted():
    result = metrics_text.fillers("matlab yaani we should save water", speaking_span=60.0)
    assert result["breakdown"] == {"matlab": 1, "yaani": 1}


# --- repetition, vocabulary, completion ------------------------------------

def test_repetition_finds_repeated_phrases_and_ignores_pure_stopwords():
    text = "my school is good my school is good and the and the"
    result = metrics_text.repetition(text)
    assert "my school" in result["bigrams"]
    assert "and the" not in result["bigrams"]     # stopword-only bigram
    assert "my school is" in result["trigrams"]


def test_vocabulary_counts_words_outside_the_common_list():
    result = metrics_text.vocabulary("the cat sat photosynthesis constitution")
    assert result["rare_count"] == 2
    assert result["total"] == 5 and result["unique"] == 5
    assert result["ttr"] == 1.0


def test_completion_flags_running_out_of_content():
    short = metrics_text.completion(words([("a", 0.0, 20.0)]), 21.0, target_seconds=90)
    assert short["ran_out"] is True and short["went_full_distance"] is False

    full = metrics_text.completion(words([("a", 0.0, 88.0)]), 89.0, target_seconds=90)
    assert full["ran_out"] is False and full["went_full_distance"] is True


def test_long_trailing_silence_counts_as_running_out():
    result = metrics_text.completion(words([("a", 0.0, 55.0)]), 70.0, target_seconds=60)
    assert result["ran_out"] is True


# --- baseline calibration ---------------------------------------------------

def hist(n, pitch_std=40.0, rms=0.10):
    return [{"audio": {"pitch": {"std_hz": pitch_std, "mean_hz": 260.0},
                       "volume": {"mean_rms": rms}}} for _ in range(n)]


def test_pitch_and_volume_stay_calibrating_until_three_sessions():
    for n in (0, 1, 2):
        norm = baseline.compare(
            {"available": True, "pitch": {"available": True, "std_hz": 10.0},
             "volume": {"available": True, "mean_rms": 0.05}},
            baseline.build(hist(n)),
        )
        assert norm["calibrating"] is True
        assert norm["pitch"]["status"] == "calibrating"


def test_monotone_is_relative_to_the_childs_own_baseline():
    base = baseline.build(hist(3, pitch_std=40.0))
    flat = baseline.compare(
        {"available": True, "pitch": {"available": True, "std_hz": 20.0},
         "volume": {"available": True, "mean_rms": 0.10}}, base)
    assert flat["calibrating"] is False and flat["pitch"]["status"] == "monotone"

    # The identical raw pitch is NOT monotone for a child whose baseline is lower.
    quiet_base = baseline.build(hist(3, pitch_std=22.0))
    same = baseline.compare(
        {"available": True, "pitch": {"available": True, "std_hz": 20.0},
         "volume": {"available": True, "mean_rms": 0.10}}, quiet_base)
    assert same["pitch"]["status"] == "typical"


def test_calibrating_metrics_are_withheld_from_the_prompt():
    lines = baseline.summarise_for_prompt(
        baseline.compare({"available": True, "pitch": {"available": True, "std_hz": 5.0},
                          "volume": {"available": True, "mean_rms": 0.01}},
                         baseline.build(hist(1))))
    assert len(lines) == 1 and "do not comment" in lines[0]


# --- feedback selection -----------------------------------------------------

BASE_METRICS = {
    "duration_s": 88.0, "has_word_timestamps": True,
    "pace": {"wpm": 125.0, "band": "typical", "word_count": 180, "speaking_span_s": 86.0},
    "fillers": {"total": 1, "per_minute": 0.7, "most_common": "um", "reliable": True, "heavy": False},
    "pauses": {"count": 1, "longest": 0.9, "in_first_15s": 0, "weak_opening": False,
               "went_blank": False, "distribution": {"first": 1, "middle": 0, "last": 0}},
    "repetition": {"heavy": False, "bigrams": {}, "trigrams": {}},
    "vocabulary": {"rare_count": 2, "examples": ["assembly"]},
    "completion": {"spoken_until_s": 86.0, "target_seconds": 90, "coverage": 0.96,
                   "trailing_silence_s": 0.5, "ran_out": False, "went_full_distance": True},
}
GOOD_IDEAS = {"available": True, "specificity": 4, "personal_stake": 4, "reasoning": 4,
              "angle": 4, "development": 4, "on_topic": 5, "structure": 4,
              "has_opening": True, "has_ending": True, "distinct_points": 3,
              "used_example": True, "main_idea": "x", "strongest_moment": "y", "biggest_opening": "z"}
STEADY = {"calibrating": False, "pitch": {"status": "typical", "ratio": 1.0},
          "volume": {"status": "typical", "ratio": 1.0, "trails_off": False}}


def test_focus_follows_the_documented_priority_order():
    m = dict(BASE_METRICS)
    m["completion"] = {**BASE_METRICS["completion"], "ran_out": True}
    m["pace"] = {**BASE_METRICS["pace"], "band": "rushing"}
    m["fillers"] = {**BASE_METRICS["fillers"], "heavy": True}
    assert feedback.choose_focus(m, GOOD_IDEAS, STEADY, "impromptu")[0] == "ran_out"

    m["completion"] = BASE_METRICS["completion"]
    assert feedback.choose_focus(m, GOOD_IDEAS, STEADY, "impromptu")[0] == "rushing"

    m["pace"] = BASE_METRICS["pace"]
    assert feedback.choose_focus(m, GOOD_IDEAS, STEADY, "impromptu")[0] == "fillers"


def test_thin_development_is_forgiven_in_impromptu_but_flagged_when_prepared():
    thin = {**GOOD_IDEAS, "development": 3}
    assert feedback.choose_focus(BASE_METRICS, thin, STEADY, "impromptu")[0] != "development"
    assert feedback.choose_focus(BASE_METRICS, thin, STEADY, "prepared")[0] == "development"


def test_pitch_and_volume_never_become_the_focus_while_calibrating():
    calibrating = {"calibrating": True, "pitch": {}, "volume": {}}
    monotone = {"calibrating": False, "pitch": {"status": "monotone", "ratio": 0.5},
                "volume": {"status": "typical", "trails_off": True}}
    assert feedback.choose_focus(BASE_METRICS, GOOD_IDEAS, calibrating, "impromptu")[0] == "keep_going"
    assert feedback.choose_focus(BASE_METRICS, GOOD_IDEAS, monotone, "impromptu")[0] == "monotone"


def test_a_filler_free_transcript_is_never_praised_for_being_filler_free():
    m = {**BASE_METRICS,
         "fillers": {"total": 0, "per_minute": 0.0, "most_common": None,
                     "reliable": False, "heavy": False}}
    win, _ = feedback.choose_win(m, {"available": False}, STEADY, focus="keep_going")
    assert win != "few_fillers"


def test_the_praise_never_contradicts_the_correction():
    rushed = {**BASE_METRICS, "pace": {**BASE_METRICS["pace"], "band": "rushing"}}
    win, _ = feedback.choose_win(rushed, {"available": False}, STEADY, focus="rushing")
    assert win != "steady_pace"


def test_badges_count_a_consecutive_day_streak():
    b = feedback.build_badges(3, ["2026-08-26T10:00:00", "2026-08-27T10:00:00",
                                  "2026-08-28T09:00:00"], topics_done=3)
    assert b["streak_days"] == 3

    broken = feedback.build_badges(2, ["2026-08-20T10:00:00", "2026-08-28T10:00:00"], 2)
    assert broken["streak_days"] == 1


# --- idea scoring plumbing ---------------------------------------------------

def test_json_is_extracted_through_fences_and_prose():
    assert ideas._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ideas._extract_json('Sure, here you go: {"a": 1} hope that helps') == {"a": 1}
    assert ideas._extract_json("no json at all") is None


def test_out_of_range_scores_are_clamped_and_missing_ones_rejected():
    full = {d: 9 for d in ideas.DIMENSIONS}
    assert ideas._normalise(full)["specificity"] == 5
    partial = {d: 3 for d in ideas.DIMENSIONS if d != "angle"}
    assert ideas._normalise(partial) is None


def test_mode_weighting_forgives_structure_in_impromptu():
    scores = {"specificity": 3, "personal_stake": 3, "reasoning": 3, "angle": 3,
              "development": 1, "on_topic": 5, "structure": 1}
    impromptu = ideas.weighted_score(scores, "impromptu")["out_of_100"]
    prepared = ideas.weighted_score(scores, "prepared")["out_of_100"]
    assert impromptu > prepared


# --- storage resilience -----------------------------------------------------

def test_database_rebuilds_its_schema_if_the_file_disappears(tmp_path, monkeypatch):
    """A missing database file must not 500 every request until a restart."""
    from app import config, db as db_mod

    path = tmp_path / "coach.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    db_mod.init_db()
    parent = db_mod.upsert_parent("sub-1", "a@example.com", "A Parent")
    child = db_mod.create_child(parent["id"], "Aisha", "9-11")
    assert db_mod.session_count(child) == 0

    path.unlink()                        # the file vanishes mid-run
    assert db_mod.session_count(child) == 0     # must not raise


def test_a_parent_cannot_read_another_parents_child(tmp_path, monkeypatch):
    from app import config, db as db_mod

    path = tmp_path / "coach.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    db_mod.init_db()

    mine = db_mod.upsert_parent("sub-a", "a@example.com", "A")
    theirs = db_mod.upsert_parent("sub-b", "b@example.com", "B")
    child = db_mod.create_child(mine["id"], "Aisha", "9-11")

    assert db_mod.get_child(child, mine["id"]) is not None
    assert db_mod.get_child(child, theirs["id"]) is None
    # deleting someone else's child must be a no-op, not a wipe
    assert db_mod.delete_child(child, theirs["id"]) == []
    assert db_mod.get_child(child, mine["id"]) is not None


def test_siblings_keep_separate_histories(tmp_path, monkeypatch):
    """The bug that motivated accounts: shared baselines across two voices."""
    from app import config, db as db_mod

    path = tmp_path / "coach.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    db_mod.init_db()

    parent = db_mod.upsert_parent("sub-a", "a@example.com", "A")
    older = db_mod.create_child(parent["id"], "Aisha", "12-14")
    younger = db_mod.create_child(parent["id"], "Zaid", "6-8")

    db_mod.mark_topic_used(older, 42)
    assert db_mod.used_topic_ids(older) == {42}
    assert db_mod.used_topic_ids(younger) == set()

    db_mod.record_consent(older, "A Parent")
    assert db_mod.has_consent(older) is True
    assert db_mod.has_consent(younger) is False


# --- sign-in safety ----------------------------------------------------------

def test_dev_login_switches_itself_off_once_google_is_configured(monkeypatch):
    """The local bypass must never be reachable on a properly configured server."""
    from app import auth, config

    monkeypatch.setattr(auth, "ALLOW_DEV_LOGIN", True)

    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "")
    assert auth.dev_login_available() is True

    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "secret")
    assert auth.dev_login_available() is False

    monkeypatch.setattr(auth, "ALLOW_DEV_LOGIN", False)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    assert auth.dev_login_available() is False


# --- backend portability -----------------------------------------------------

def test_placeholders_translate_for_postgres_without_touching_strings(monkeypatch):
    """`?` becomes `%s`, but a literal question mark inside a string must survive."""
    from app import db as db_mod

    monkeypatch.setattr(db_mod, "USE_POSTGRES", False)
    assert db_mod._adapt("SELECT * FROM t WHERE a = ?") == "SELECT * FROM t WHERE a = ?"

    monkeypatch.setattr(db_mod, "USE_POSTGRES", True)
    assert db_mod._adapt("SELECT * FROM t WHERE a = ?") == "SELECT * FROM t WHERE a = %s"
    assert db_mod._adapt("SELECT ?, 'why?' FROM t") == "SELECT %s, 'why?' FROM t"


def test_schema_uses_the_right_autoincrement_per_backend(monkeypatch):
    from app import db as db_mod

    monkeypatch.setattr(db_mod, "USE_POSTGRES", False)
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" in db_mod._schema_sql()

    monkeypatch.setattr(db_mod, "USE_POSTGRES", True)
    sql = db_mod._schema_sql()
    assert "BIGSERIAL PRIMARY KEY" in sql
    assert "AUTOINCREMENT" not in sql
    assert "{SERIAL}" not in sql
