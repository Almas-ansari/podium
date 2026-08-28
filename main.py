"""Podium - a speaking and thinking coach for children aged 6 to 14.

Run: uvicorn main:app --reload

A parent signs in with Google and creates a profile per child. Everything a
child accumulates hangs off their profile, so siblings sharing one laptop keep
genuinely separate baselines.
"""
import json
import logging
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import auth, charts, db, feedback as feedback_mod, ideas as ideas_mod, metrics_text, pipeline, topics
from app.config import (
    AGE_BANDS, BASE_DIR, MAX_CHILDREN_PER_PARENT, MODES, PREP_CHOICES, SESSION_SECRET,
    SECURE_COOKIES, TIMER_CHOICES, google_configured, has_api_key,
)
from app.groq_client import TranscriptionError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("coach")

app = FastAPI(title="Podium", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax",
    https_only=SECURE_COOKIES, max_age=60 * 60 * 24 * 30,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # Groq's own file size ceiling


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    if not has_api_key():
        log.warning("GROQ_API_KEY is not set - recording will fail until it is.")


# --- shared helpers -------------------------------------------------------

def valid(value: Optional[str], allowed: tuple, default: str) -> str:
    return value if value in allowed else default


def prefs(request: Request) -> dict[str, Any]:
    stored = request.session.get("prefs")
    return stored if isinstance(stored, dict) else {}


def save_prefs(request: Request, **updates: Any) -> dict[str, Any]:
    merged = {**prefs(request), **updates}
    request.session["prefs"] = merged
    return merged


def base_context(request: Request) -> dict[str, Any]:
    """Identity for the header, on every page."""
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    return {
        "parent": parent,
        "child": child,
        "children": db.list_children(parent["id"]) if parent else [],
    }


def render(request: Request, template: str, context: dict[str, Any]):
    return templates.TemplateResponse(request, template, {**base_context(request), **context})


def require_child(request: Request):
    """(child, redirect) - redirect is set when the caller cannot continue."""
    parent = auth.current_parent(request)
    if not parent:
        return None, RedirectResponse("/signin", status_code=303)
    child = auth.active_child(request)
    if not child:
        return None, RedirectResponse("/children", status_code=303)
    if not child["consent_at"]:
        return None, RedirectResponse("/consent", status_code=303)
    return child, None


# --- sign in --------------------------------------------------------------

@app.get("/guide", response_class=HTMLResponse)
def guide(request: Request):
    """How it works. Public, and linked from the nav once signed in."""
    return render(request, "guide.html", {
        "showcase": topics.showcase(18),
        "topic_count": len(topics.all_topics()),
    })


@app.get("/signin", response_class=HTMLResponse)
def signin(request: Request):
    if auth.parent_id(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "signin.html", {
        "google_ready": google_configured(),
        "dev_login": auth.dev_login_available(),
        "error": request.query_params.get("error"),
    })


@app.get("/auth/google")
async def google_login(request: Request):
    if not google_configured():
        return RedirectResponse("/signin?error=not_configured", status_code=303)
    redirect_uri = str(request.url_for("auth_callback"))
    if redirect_uri.startswith("http://") and request.headers.get("x-forwarded-proto") == "https":
        # Belt and braces if the proxy headers are not being trusted upstream.
        redirect_uri = "https://" + redirect_uri[len("http://"):]
    log.info("google sign-in redirect_uri=%s", redirect_uri)
    return await auth.oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    if not google_configured():
        return RedirectResponse("/signin?error=not_configured", status_code=303)
    try:
        token = await auth.oauth.google.authorize_access_token(request)
    except Exception as exc:
        log.error("google sign-in failed: %s: %s", type(exc).__name__, exc)
        log.error("  callback url seen as: %s", request.url)
        log.error("  session cookie present: %s", "session" in request.cookies)
        return RedirectResponse("/signin?error=failed", status_code=303)

    info = token.get("userinfo") or {}
    if not info.get("sub") or not info.get("email"):
        return RedirectResponse("/signin?error=failed", status_code=303)

    parent = db.upsert_parent(
        google_sub=str(info["sub"]), email=str(info["email"]),
        name=str(info.get("name") or ""), picture=str(info.get("picture") or ""),
    )
    auth.sign_in(request, parent)
    return RedirectResponse("/", status_code=303)


@app.post("/auth/dev")
def dev_login(request: Request, email: str = Form("parent@example.com")):
    """Local-only sign-in for when Google is not configured. Off unless ALLOW_DEV_LOGIN."""
    if not auth.dev_login_available():
        raise HTTPException(status_code=404, detail="Not found")
    clean = (email or "").strip()[:120] or "parent@example.com"
    parent = db.upsert_parent(
        google_sub=f"dev:{clean}", email=clean, name=clean.split("@")[0].title(), picture="",
    )
    auth.sign_in(request, parent)
    return RedirectResponse("/", status_code=303)


@app.get("/signout")
def signout(request: Request):
    auth.sign_out(request)
    return RedirectResponse("/signin", status_code=303)


# --- child profiles -------------------------------------------------------

@app.get("/children", response_class=HTMLResponse)
def children_screen(request: Request):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)

    rows = db.list_children(parent["id"])
    summaries = []
    for row in rows:
        sessions = db.list_sessions(row["id"])
        summaries.append({
            "row": row,
            "sessions": len(sessions),
            "last": sessions[-1]["created_at"][:10] if sessions else None,
        })

    return render(request, "children.html", {
        "summaries": summaries,
        "age_bands": AGE_BANDS,
        "can_add": len(rows) < MAX_CHILDREN_PER_PARENT,
        "max_children": MAX_CHILDREN_PER_PARENT,
        "error": request.query_params.get("error"),
    })


@app.post("/children")
def create_child(request: Request, name: str = Form(...), age_band: str = Form(...)):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    if not name.strip():
        return RedirectResponse("/children?error=name", status_code=303)
    if len(db.list_children(parent["id"])) >= MAX_CHILDREN_PER_PARENT:
        return RedirectResponse("/children?error=limit", status_code=303)

    child_id = db.create_child(parent["id"], name, valid(age_band, AGE_BANDS, "9-11"))
    auth.select_child(request, child_id)
    return RedirectResponse("/consent", status_code=303)


# Pages that belong to one specific session. Carrying a child switch onto these
# would land you on another child's session id, which 404s.
CHILD_SPECIFIC_PREFIXES = ("/feedback/", "/parent/session/", "/speak", "/prep")


@app.post("/children/{child_id}/select")
def choose_child(request: Request, child_id: str, next: str = Form("/")):
    if not auth.select_child(request, child_id):
        return RedirectResponse("/children?error=missing", status_code=303)

    target = next if next.startswith("/") and not next.startswith("//") else "/"
    if any(target.startswith(prefix) for prefix in CHILD_SPECIFIC_PREFIXES):
        target = "/"
    return RedirectResponse(target, status_code=303)


@app.post("/children/{child_id}/edit")
def edit_child(request: Request, child_id: str, name: str = Form(...),
               age_band: str = Form(...)):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    if not name.strip():
        return RedirectResponse("/children?error=name", status_code=303)

    db.update_child(child_id, parent["id"], name, valid(age_band, AGE_BANDS, "9-11"))
    return RedirectResponse("/children?saved=1", status_code=303)


@app.post("/children/{child_id}/delete")
def remove_child(request: Request, child_id: str, confirm: str = Form(None)):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    if confirm != "DELETE":
        return RedirectResponse("/children?error=confirm", status_code=303)

    db.delete_child(child_id, parent["id"])
    if request.session.get(auth.CHILD_KEY) == child_id:
        request.session.pop(auth.CHILD_KEY, None)
    return RedirectResponse("/children?deleted=1", status_code=303)


# --- screens --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    parent = auth.current_parent(request)
    if not parent:
        return render(request, "landing.html", {
            "google_ready": google_configured(),
            "dev_login": auth.dev_login_available(),
            # Real topics from the shipped bank, so the marquee shows the actual
            # product rather than invented marketing copy.
            "showcase": topics.showcase(18),
            "topic_count": len(topics.all_topics()),
        })

    child = auth.active_child(request)
    if not child:
        return RedirectResponse("/children", status_code=303)

    return render(request, "welcome.html", {
        "sessions": db.session_count(child["id"]),
        "has_consent": bool(child["consent_at"]),
        "just_added": request.query_params.get("added") == "1",
        "api_key_missing": not has_api_key(),
    })


@app.get("/practise", response_class=HTMLResponse)
def practise(request: Request):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    child = auth.active_child(request)
    if not child:
        return RedirectResponse("/children", status_code=303)

    return render(request, "home.html", {
        "age_bands": AGE_BANDS,
        "modes": MODES,
        "prefs": prefs(request),
        "sessions": db.session_count(child["id"]),
        "has_consent": bool(child["consent_at"]),
        "api_key_missing": not has_api_key(),
    })


@app.post("/start")
def start(request: Request, age_band: str = Form(...), mode: str = Form(...)):
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    if not child:
        return RedirectResponse("/signin", status_code=303)

    band = valid(age_band, AGE_BANDS, "9-11")
    save_prefs(request, mode=valid(mode, MODES, "impromptu"))
    if band != child["age_band"]:
        db.set_age_band(child["id"], band)

    return RedirectResponse("/topic" if child["consent_at"] else "/consent", status_code=303)


@app.get("/consent", response_class=HTMLResponse)
def consent_form(request: Request):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    child = auth.active_child(request)
    if not child:
        return RedirectResponse("/children", status_code=303)

    return render(request, "consent.html", {
        "already": bool(child["consent_at"]),
        "error": request.query_params.get("error"),
    })


@app.post("/consent")
def consent_submit(request: Request, parent_name: str = Form(...), agree: str = Form(None)):
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    if not child:
        return RedirectResponse("/signin", status_code=303)
    if not agree or not parent_name.strip():
        return RedirectResponse("/consent?error=1", status_code=303)

    db.record_consent(child["id"], parent_name)
    return RedirectResponse("/?added=1", status_code=303)


@app.get("/topic", response_class=HTMLResponse)
def topic_screen(request: Request, exclude: Optional[int] = None,
                 seconds: Optional[int] = None, minutes: Optional[int] = None):
    child, redirect = require_child(request)
    if redirect:
        return redirect

    # "Different topic" submits the form, so the length choices survive the swap.
    if seconds in TIMER_CHOICES:
        save_prefs(request, seconds=seconds)
    if minutes in PREP_CHOICES:
        save_prefs(request, prep=minutes)

    age_band = valid(child["age_band"], AGE_BANDS, "9-11")
    mode = valid(prefs(request).get("mode"), MODES, "impromptu")
    topic = topics.pick(child["id"], age_band, mode, exclude_id=exclude)
    done, total = topics.band_stats(child["id"], age_band, mode)

    return render(request, "topic.html", {
        "topic": topic, "mode": mode, "age_band": age_band,
        "timer_choices": TIMER_CHOICES, "prep_choices": PREP_CHOICES,
        "seconds": prefs(request).get("seconds", 90),
        "prep": prefs(request).get("prep", 5),
        "done": done, "total": total,
    })


@app.get("/prep", response_class=HTMLResponse)
def prep_screen(request: Request, topic_id: int, minutes: int = 5, seconds: int = 90):
    child, redirect = require_child(request)
    if redirect:
        return redirect

    topic = topics.by_id(topic_id)
    if not topic:
        return RedirectResponse("/topic", status_code=303)

    minutes = minutes if minutes in PREP_CHOICES else 5
    seconds = seconds if seconds in TIMER_CHOICES else 90
    save_prefs(request, seconds=seconds, prep=minutes)

    return render(request, "prep.html",
                  {"topic": topic, "minutes": minutes, "seconds": seconds})


@app.get("/speak", response_class=HTMLResponse)
def speak_screen(request: Request, topic_id: int, seconds: int = 90):
    child, redirect = require_child(request)
    if redirect:
        return redirect

    topic = topics.by_id(topic_id)
    if not topic:
        return RedirectResponse("/topic", status_code=303)

    seconds = seconds if seconds in TIMER_CHOICES else 90
    save_prefs(request, seconds=seconds)

    return render(request, "speak.html", {
        "topic": topic, "seconds": seconds,
        "mode": valid(prefs(request).get("mode"), MODES, "impromptu"),
    })


@app.post("/api/session")
async def create_session(
    request: Request,
    audio: UploadFile = File(...),
    topic_id: int = Form(...),
    seconds: int = Form(90),
):
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    if not child:
        return JSONResponse({"error": "Please sign in again.", "redirect": "/signin"},
                            status_code=401)

    # Consent is enforced here, in the only code path that can record a child.
    if not child["consent_at"]:
        return JSONResponse({"error": "A parent must give consent first.", "redirect": "/consent"},
                            status_code=403)

    topic = topics.by_id(topic_id)
    if not topic:
        return JSONResponse({"error": "Unknown topic."}, status_code=400)

    payload = await audio.read()
    if not payload:
        return JSONResponse({"error": "The recording was empty."}, status_code=400)
    if len(payload) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "That recording is too long to upload."}, status_code=413)

    age_band = valid(child["age_band"], AGE_BANDS, topic["age_band"])
    mode = valid(prefs(request).get("mode"), MODES, "impromptu")
    target = seconds if seconds in TIMER_CHOICES else 90

    try:
        result = pipeline.process(child["id"], age_band, mode, topic, target, payload)
    except pipeline.NoSpeechError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except TranscriptionError as exc:
        log.error("transcription failed: %s", exc)
        return JSONResponse(
            {"error": "We could not process that recording. Please try once more."},
            status_code=502,
        )
    except Exception:
        log.exception("session processing failed")
        return JSONResponse({"error": "Something went wrong on our side."}, status_code=500)

    return {"redirect": f"/feedback/{result['session_id']}"}


@app.get("/feedback/{session_id}", response_class=HTMLResponse)
def feedback_screen(request: Request, session_id: int):
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    if not child:
        return RedirectResponse("/signin", status_code=303)

    row = db.get_session(session_id, child["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    fb = json.loads(row["feedback_json"])
    context = _report_context(child["id"], row)
    context.update({"fb": fb, "badges": fb.get("badges", {})})
    return render(request, "feedback.html", context)


# --- parent dashboard -----------------------------------------------------


def _practice_days(rows) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        day = row["created_at"][:10]
        counts[day] = counts.get(day, 0) + 1
    return counts


def _personal_bests(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Records worth celebrating, each tied to the speech that set it."""
    out: list[dict[str, Any]] = []

    def best(label: str, unit: str, key, pick_max: bool):
        scored = [(key(h), h) for h in history]
        scored = [(v, h) for v, h in scored if isinstance(v, (int, float))]
        if not scored:
            return
        value, entry = (max if pick_max else min)(scored, key=lambda pair: pair[0])
        out.append({
            "label": label, "value": round(float(value), 1), "unit": unit,
            "topic": entry["row"]["topic_text"], "session_id": entry["row"]["id"],
        })

    best("Longest speech", "s", lambda h: h["row"]["duration"], True)
    best("Most words", "", lambda h: h["metrics"].get("pace", {}).get("word_count"), True)
    best("Cleanest delivery", "/min", lambda h: h["metrics"].get("fillers", {}).get("per_minute"), False)
    best("Best ideas", "/100",
         lambda h: h["ideas"].get("overall", {}).get("out_of_100") if h["ideas"].get("available") else None,
         True)
    return out


def _focus_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What was flagged each time, newest first - the coaching thread over time."""
    out = []
    for entry in reversed(history):
        key = entry["feedback"].get("focus_key")
        if not key:
            continue
        out.append({
            "n": entry["n"],
            "date": entry["row"]["created_at"][:10],
            "label": feedback_mod.FOCUS_LABELS.get(key, key.replace("_", " ")),
            "topic": entry["row"]["topic_text"],
            "session_id": entry["row"]["id"],
        })
    return out[:8]


def _best_moments(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Things the child actually said that were worth hearing."""
    out = []
    for entry in reversed(history):
        moment = entry["ideas"].get("strongest_moment")
        if not moment or len(moment) < 12:
            continue
        out.append({
            "quote": moment,
            "topic": entry["row"]["topic_text"],
            "date": entry["row"]["created_at"][:10],
            "session_id": entry["row"]["id"],
        })
    return out[:4]


def _coverage(rows) -> dict[str, Any]:
    """Breadth: which categories and modes have been tried."""
    from collections import Counter

    cats: Counter = Counter()
    modes: Counter = Counter()
    for row in rows:
        modes[row["mode"]] += 1
        topic = topics.by_id(row["topic_id"]) if row["topic_id"] else None
        if topic:
            cats[topic["category"]] += 1

    total = sum(cats.values()) or 1
    return {
        "categories": [
            {"name": name.replace("-", " ").title(), "count": count,
             "pct": round(count / total * 100)}
            for name, count in cats.most_common(8)
        ],
        "modes": dict(modes),
        "spoken_seconds": sum(float(r["duration"] or 0) for r in rows),
        "words": 0,
    }


@app.get("/parent", response_class=HTMLResponse)
def parent_dashboard(request: Request):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)

    child = auth.active_child(request)
    if not child:
        return RedirectResponse("/children", status_code=303)

    rows = db.list_sessions(child["id"])
    labels, pace, filler, pauses, idea_scores = [], [], [], [], []
    history: list[dict[str, Any]] = []

    for n, row in enumerate(rows, start=1):
        metrics = json.loads(row["metrics_json"] or "{}")
        try:
            idea = json.loads(row["ideas_json"] or "{}")
        except json.JSONDecodeError:
            idea = {}

        labels.append(f"#{n}")
        pace.append(metrics.get("pace", {}).get("wpm"))
        filler.append(metrics.get("fillers", {}).get("per_minute"))
        pauses.append(metrics.get("pauses", {}).get("count"))
        idea_scores.append(idea.get("overall", {}).get("out_of_100") if idea.get("available") else None)

        history.append({
            "row": row, "metrics": metrics, "ideas": idea,
            "feedback": json.loads(row["feedback_json"] or "{}"), "n": n,
        })

    dimension_rows = []
    scored = [h["ideas"] for h in history if h["ideas"].get("available")]
    if scored:
        recent = scored[-5:]
        for dim in ideas_mod.DIMENSIONS:
            avg = sum(float(s.get(dim, 0)) for s in recent) / len(recent)
            dimension_rows.append((dim.replace("_", " ").title(), avg, 5.0))

    rendered = {
        "pace": charts.line_chart("Pace", pace, labels, band=(100, 150),
                                  band_label="typical for a child", unit=" wpm"),
        "fillers": charts.line_chart("Filler words", filler, labels, unit="/min"),
        "pauses": charts.line_chart("Long pauses", pauses, labels, unit=""),
        "ideas": charts.line_chart("Idea quality", idea_scores, labels, unit="/100",
                                   domain=(0, 100)),
        "dimensions": charts.bars("Idea dimensions (last 5 sessions, out of 5)", dimension_rows),
    }

    fb = history[-1]["feedback"] if history else {}
    return render(request, "parent.html", {
        "history": list(reversed(history)),
        "charts": rendered,
        "badges": fb.get("badges", {}),
        "total": len(history),
        "headline": feedback_mod.headline(history),
        "calendar": charts.calendar(_practice_days(rows)),
        "bests": _personal_bests(history),
        "focus_history": _focus_history(history),
        "moments": _best_moments(history),
        "coverage": _coverage(rows),
        "total_words": sum(h["metrics"].get("pace", {}).get("word_count", 0) for h in history),
        "trends": _stat_trends(history),
        "focus_now": feedback_mod.FOCUS_LABELS.get(fb.get("focus_key"), None),
    })


def _stat_trends(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Latest value against the first speech, per headline stat.

    A number on its own tells a parent nothing. A number with a direction tells
    them whether to keep going.
    """
    if len(history) < 2:
        return {}

    def at(entry: dict, *path: str) -> Optional[float]:
        node: Any = entry
        for key in path:
            node = node.get(key, {}) if isinstance(node, dict) else None
        return float(node) if isinstance(node, (int, float)) else None

    specs = {
        "pace": (("metrics", "pace", "wpm"), "band"),
        "fillers": (("metrics", "fillers", "per_minute"), "lower"),
        "ideas": (("metrics",), "higher"),
    }
    out: dict[str, Any] = {}

    for key, (path, better) in specs.items():
        if key == "ideas":
            first = history[0]["ideas"].get("overall", {}).get("out_of_100") if history[0]["ideas"].get("available") else None
            last = history[-1]["ideas"].get("overall", {}).get("out_of_100") if history[-1]["ideas"].get("available") else None
        else:
            first, last = at(history[0], *path), at(history[-1], *path)
        if first is None or last is None:
            continue

        delta = last - first
        if better == "band":
            near = _pace_distance(last) or 0.0
            was = _pace_distance(first) or 0.0
            direction = "better" if near < was - 4 else ("worse" if near > was + 4 else "steady")
        else:
            threshold = max(abs(first) * 0.1, 0.5)
            improved = delta < -threshold if better == "lower" else delta > threshold
            worsened = delta > threshold if better == "lower" else delta < -threshold
            direction = "better" if improved else ("worse" if worsened else "steady")

        out[key] = {"delta": round(delta, 1), "direction": direction}
    return out


def _report_context(child_id: str, row) -> dict[str, Any]:
    """Everything the detailed report needs for one session.

    Shared by the report tab on the feedback screen and the dashboard's session
    page, so the two can never drift apart.
    """
    metrics = json.loads(row["metrics_json"] or "{}")
    try:
        idea = json.loads(row["ideas_json"] or "{}")
    except json.JSONDecodeError:
        idea = {}
    try:
        words = json.loads(row["words_json"] or "[]")
    except json.JSONDecodeError:
        words = []

    dimension_rows = []
    if idea.get("available"):
        for dim in ideas_mod.DIMENSIONS:
            dimension_rows.append((dim.replace("_", " ").title(), float(idea.get(dim, 0)), 5.0))

    duration = float(row["duration"] or 0.0)
    audio = metrics.get("audio", {}) or {}

    return {
        "session": row,
        "metrics": metrics,
        "ideas": idea,
        "feedback": json.loads(row["feedback_json"] or "{}"),
        "dimensions": charts.bars("Idea dimensions (out of 5)", dimension_rows),
        # Where the pauses, fillers and quiet patches actually fell in this speech.
        "speech_map": charts.speech_map(
            envelope=audio.get("envelope") or [],
            pauses=metrics.get("pauses", {}).get("pauses") or [],
            fillers=metrics_text.filler_positions(words),
            duration=duration,
        ),
        "pace_segments": charts.segment_bars(
            "Pace across the speech", _pace_segments(words, duration),
            band=(100, 150), unit=" wpm",
        ),
        "summary": feedback_mod.session_summary(
            metrics, idea, metrics.get("normalised", {}), row["mode"]),
        "comparison": _session_comparison(child_id, row["id"], metrics, idea),
        "session_number": _session_number(child_id, row["id"]),
        # Playback comes from the family's own browser storage, so whether a
        # recording exists is decided client-side, not here.
    }


@app.get("/parent/session/{session_id}", response_class=HTMLResponse)
def parent_session(request: Request, session_id: int):
    parent = auth.current_parent(request)
    child = auth.active_child(request) if parent else None
    if not child:
        return RedirectResponse("/signin", status_code=303)

    row = db.get_session(session_id, child["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    return render(request, "session.html", _report_context(child["id"], row))


def _pace_segments(words: list[dict], duration: float,
                   window: float = 15.0) -> list[tuple[str, float]]:
    """Words per minute in each 15 second slice, so a mid-speech sprint shows up."""
    if not words or duration <= 0:
        return []

    slices = max(int(duration // window) + (1 if duration % window > 4 else 0), 1)
    counts = [0] * slices
    for w in words:
        idx = min(int(float(w["start"]) // window), slices - 1)
        counts[idx] += 1

    out = []
    for i, count in enumerate(counts):
        start = i * window
        span = min(window, duration - start)
        if span < 4:            # a stub tail slice would show a meaningless spike
            continue
        out.append((f"{int(start)}-{int(start + span)}s", count / span * 60.0))
    return out


def _session_number(child_id: str, session_id: int) -> int:
    """Which speech this was, counting from the child's first."""
    for n, row in enumerate(db.list_sessions(child_id), start=1):
        if row["id"] == session_id:
            return n
    return 0


def _pace_distance(wpm: Optional[float]) -> Optional[float]:
    """How far outside the comfortable 100-150 wpm band a pace sits."""
    if wpm is None:
        return None
    if 100 <= wpm <= 150:
        return 0.0
    return min(abs(wpm - 100), abs(wpm - 150))


def _session_comparison(child_id: str, session_id: int,
                        metrics: dict, ideas: dict) -> list[dict[str, Any]]:
    """This speech against the average of the child's other speeches.

    A pace of 168 wpm means nothing on its own. "168, against your usual 131"
    is the number a parent can actually act on.
    """
    others_pace, others_fill, others_pause, others_ideas = [], [], [], []
    for row in db.list_sessions(child_id):
        if row["id"] == session_id:
            continue
        try:
            other = json.loads(row["metrics_json"] or "{}")
            other_ideas = json.loads(row["ideas_json"] or "{}")
        except json.JSONDecodeError:
            continue
        for value, bucket in (
            (other.get("pace", {}).get("wpm"), others_pace),
            (other.get("fillers", {}).get("per_minute"), others_fill),
            (other.get("pauses", {}).get("count"), others_pause),
            (other_ideas.get("overall", {}).get("out_of_100") if other_ideas.get("available") else None,
             others_ideas),
        ):
            if isinstance(value, (int, float)):
                bucket.append(float(value))

    def avg(values: list[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    specs = [
        ("Pace", metrics.get("pace", {}).get("wpm"), avg(others_pace), " wpm", "band"),
        ("Filler words", metrics.get("fillers", {}).get("per_minute"), avg(others_fill), "/min", "lower"),
        ("Long pauses", metrics.get("pauses", {}).get("count"), avg(others_pause), "", "lower"),
        ("Idea quality",
         ideas.get("overall", {}).get("out_of_100") if ideas.get("available") else None,
         avg(others_ideas), "/100", "higher"),
    ]

    rows = []
    for label, value, average, unit, better in specs:
        if value is None:
            continue
        row: dict[str, Any] = {
            "label": label, "value": value, "average": average, "unit": unit,
            "direction": "none", "delta": None,
        }
        if average is not None:
            delta = float(value) - average
            row["delta"] = delta
            if better == "band":
                near, was = _pace_distance(float(value)), _pace_distance(average)
                improved = near is not None and was is not None and near < was - 4
                worsened = near is not None and was is not None and near > was + 4
            else:
                threshold = max(abs(average) * 0.10, 0.5)
                improved = delta < -threshold if better == "lower" else delta > threshold
                worsened = delta > threshold if better == "lower" else delta < -threshold
            row["direction"] = "better" if improved else ("worse" if worsened else "steady")
        rows.append(row)
    return rows


@app.post("/parent/delete")
def delete_everything(request: Request, confirm: str = Form(None)):
    parent = auth.current_parent(request)
    if not parent:
        return RedirectResponse("/signin", status_code=303)
    if confirm != "DELETE":
        return RedirectResponse("/parent?delete=invalid", status_code=303)

    db.delete_all_for_parent(parent["id"])
    auth.sign_out(request)
    # ?wipe=1 tells the sign-in page to clear the recordings held in this browser.
    return RedirectResponse("/signin?deleted=1&wipe=1", status_code=303)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """The real icon is an inline data URI in the template; this just stops the 404s."""
    return Response(status_code=204)


@app.get("/health")
def health():
    return {
        "ok": True,
        "api_key_configured": has_api_key(),
        "google_configured": google_configured(),
        "topics": len(topics.all_topics()),
    }
