# Podium — sharper ideas, said out loud

A speaking coach for children aged 6 to 14. The child gets a topic, speaks about it into
the microphone, and gets feedback on **what** they said as well as **how** they said it.

Most speaking apps score delivery: pace, fillers, tone. Podium scores that too, but the
part it exists for is the thinking — whether the child gave a real example, backed a claim
with a reason, and explored one idea instead of touching five and dropping them. That is the
teachable half, and it is the half nearly every competing product skips.

Built by **Almas Ansari** —
[email](mailto:itsmealmas.ansari@gmail.com) ·
[LinkedIn](https://www.linkedin.com/in/almasansari0/) ·
[GitHub](https://github.com/Almas-ansari) ·
[Portfolio](https://almas-ansari-i2oeimx.gamma.site)

---

## Deploying

`Dockerfile` works as-is on any container host. Two ready-made paths:

- **Hugging Face Spaces** (recommended, no credit card, sleeps after 48 hours rather
  than 15 minutes) — create a Docker Space and use
  [`deploy/huggingface-space-README.md`](deploy/huggingface-space-README.md) as its README.
- **Render** — `render.yaml` is a blueprint; point Render at this repo and set the
  secrets in the dashboard.

Then run `python tools/export_static.py --api <backend-url>` and put `dist/` on
Cloudflare Pages, so the landing page is instant and warms the backend while people read.

## Setup

You need **one API key** (Groq, free) and **one OAuth client** (Google, free).

### 1. Groq API key

1. Sign up at **https://console.groq.com** (free, no card required).
2. Go to **API Keys → Create API Key**: **https://console.groq.com/keys**
3. Copy the key.

### 2. Google sign-in

1. Open **https://console.cloud.google.com/apis/credentials**
2. **Create credentials → OAuth client ID**, application type **Web application**
3. Under *Authorised redirect URIs* add exactly:
   `http://127.0.0.1:8000/auth/callback`
   (add your production URL there too when you deploy)
4. Copy the **Client ID** and **Client secret**

### 3. Install and configure

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill it in
```

`.env` should contain:

```
GROQ_API_KEY=gsk_...
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
SESSION_SECRET=...          # python -c "import secrets;print(secrets.token_urlsafe(48))"
```

**Trying it without Google?** Set `ALLOW_DEV_LOGIN=true` and you get a local-only sign-in
button that hands out a parent account to anyone who clicks it. Fine on your laptop, never in
production — the flag is off by default and the route 404s unless it is set.

Put the key in **`.env`**, not `.env.example`. `.env` is gitignored; `.env.example` is the
template that gets committed.

## Run

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000. The database and its schema are created on first run.

> The microphone only works over **HTTPS** or on **localhost**. That is a browser rule, not
> an app setting — a plain `http://` address on another machine will silently fail.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

26 tests covering the deterministic layer: the pause detector, pace bands, filler matching,
repetition, vocabulary, per-child baseline calibration, the feedback priority order, and the
JSON parsing that survives a badly behaved model.

---

## Accounts and child profiles

**The account belongs to the parent.** They sign in with Google and add one profile per child.
Children hold no credentials — a 7 year old should not have a password, and a 13 year old
should not be the party consenting to their own data collection. The child taps their name
from the switcher in the header.

Each profile keeps its own sessions, streak, topic rotation and — the reason this matters —
its own **pitch and volume baseline**. Two siblings sharing one laptop used to share one
browser cookie, which quietly averaged the baseline across two different voices and produced
wrong feedback for both of them. It never errored; it was just wrong. Separate profiles fix
that, and `tests/` has a regression test for it.

Every child lookup is scoped by the signed-in parent, so a stale or tampered session can never
surface another family's child.

| Table | Holds |
|---|---|
| `parents` | Google subject id, email, name, picture |
| `children` | parent id, first name, age band, consent timestamp and consenting name |
| `sessions` | one row per speech, keyed to a child |
| `topic_history` | which topics a child has already had |

Storage is SQLite. Every statement uses `?` placeholders and `RETURNING` rather than
`lastrowid`, so moving to Postgres for hosting is a driver swap rather than a rewrite.

## How it works

### The split that makes it honest

Delivery is measured **numerically in Python**. The language model is never asked to judge
how someone sounded, because it cannot hear the audio and will produce confident nonsense
about tone if invited to.

The model gets the transcript plus the already-computed numbers, and its only job is to pick
the phrasing:

```
Child age band: 9-11
Mode: impromptu
Topic: "The best thing about my school"
Duration: 74s | Pace: 168 wpm (rushing)
Fillers: 11, mostly "um" (8.9/min)
Pauses over 0.7s: 6, 4 in the first 15 seconds
Pitch variation: low (flat) vs this child's baseline
Ideas (1-5): specificity 2, personal stake 4, reasoning 2, angle 3, development 2
```

Two runs on the same audio give the same numbers. Only the sentence changes.

### What gets measured

**From the transcript and its word timestamps**

| Metric | Detail |
|---|---|
| Pace | Words per minute across the actual speaking span. Under 90 hesitant, over 170 rushing. |
| Fillers | `um, uh, er, like, so, basically, actually, matlab, yaani` — whole-word, case-insensitive. Raw count and per-minute rate. |
| Pauses | Every gap over 0.7s between adjacent words: count, longest, and **where they cluster**. Three in the first 15 seconds is a weak opening, which is a far more useful note than "you paused a lot". |
| Repetition | Repeated bigrams and trigrams, ignoring stopword-only phrases. This is how JAM is actually judged. |
| Vocabulary | Type-token ratio, plus words outside a shipped 1,000-word common list. |

**From the raw audio, locally** (`parselmouth` + `numpy`, no API calls, no audio leaves the machine)

| Metric | Detail |
|---|---|
| Volume consistency | RMS in 50 ms windows, and the drop across the final third — trailing off is very common and very fixable. |
| Pitch variation | F0 standard deviation. Low variance is monotone. |
| Speech-to-silence | Proportion of the clip that carried speech. |

### Pitch and volume are judged per child, never against a fixed threshold

A 7 year old's fundamental frequency sits far above a 13 year old's. Any absolute threshold
tells every young child they are shrieking. So each child's **first three sessions** become
their own baseline, and pitch and volume are only ever reported as deviation from it. Until
those three exist, both are marked *calibrating* and are **excluded from feedback entirely** —
they cannot be praised and cannot be corrected.

No confidence score and no emotion detection. Neither has a trustworthy model behind it, and
dressing up a composite of pace and volume as "confidence" would be a lie told to a child.

### Idea quality

Seven dimensions, scored 1–5 by the LLM from the transcript alone:

`specificity` · `personal_stake` · `reasoning` · `angle` · `development` · `on_topic` · `structure`

The two modes are weighted differently. In a **prepared** speech, weak structure and thin
development are preparation failures worth naming. In an **impromptu** speech they are the
normal cost of thinking aloud, so they carry roughly half the weight. The same speech scores
higher as impromptu than as prepared, on purpose.

Malformed JSON gets one retry, then the session degrades to delivery-only feedback rather
than inventing scores.

### What the child sees

Never a number that reads as a score. A 9 year old shown 43/100 stops speaking, and that
single design decision is the difference between a tool a child returns to and one they avoid.

Exactly three things:

1. **One specific thing they did well** — drawn from real measurements, ideally quoting what
   they actually said. "You told us your teacher stayed back to help you" beats "Great job!".
2. **One thing to try next time** — exactly one, chosen by a fixed priority order:
   *ran out of content → rushing → heavy fillers → thin development → no specifics →
   monotone → trailing volume → structure → repetition.*
3. **A streak or badge** — speeches done, days in a row, topics covered.

Idea feedback is phrased as an addition, never a verdict. *"Next time, tell us about one
Diwali you remember"* carries the same information as *"your point was generic"* and has the
opposite effect on whether the child speaks again.

Language matches the age band. The same session produces:

- **6–8:** "You told us your teacher stayed back to help you."
- **12–14:** "The moment about your teacher staying back did the work here, because it was specific enough to picture."

The parent dashboard at `/parent` is where the numbers live: trend charts for pace, filler
rate, pauses and idea quality, plus session history with transcripts and playback.

---

## Child data

We are recording minors, so India's DPDP Act 2023 applies. These are enforced in code, not
offered as settings-page checkboxes:

- **Audio never persists on the server.** The upload is written to a scratch file only because
  parselmouth reads from disk, and a `finally` block deletes it on every path including errors.
  What survives is the transcript and the numbers. The playback copy is the Opus blob
  MediaRecorder already produced, held in the family's own browser via IndexedDB
  (`static/audiostore.js`) — so recordings are per-device, and clearing browser data removes
  them. The audio does still pass through the server to reach Groq for transcription; there is
  no way around that, but it is processed and discarded rather than stored.
- **Parental consent gate** before any recording. Name and timestamp are stored. The
  `POST /api/session` handler — the only path that can record a child — rejects with 403
  without it.
- **A working delete-everything button** on the parent dashboard. It removes every session,
  transcript, measurement and consent record server-side, then clears the recordings held in
  the browser too — the server cannot reach those, so the sign-in page does it on the way out.
- **No analytics, no ad SDKs, no trackers, no CDN.** Even the fonts are the system stack rather
  than Google Fonts.
- **Two third parties, both named on the consent screen.** Google, for parent sign-in only, and
  Groq, for transcription and the feedback sentence. Google receives the parent's name, email
  and profile picture and is told nothing whatsoever about the child. Nothing about a child
  leaves the machine except the audio sent to Groq for transcription.
- **Children hold no credentials.** The account is the parent's; children are profiles under it
  and are identified by a first name and an age band, nothing more.

---

## Hosting it free, with no credit card

The app needs a real container (parselmouth rules out serverless), outbound
HTTPS, and **HTTPS serving** — browsers block microphone access on plain `http://`.

### The cold-start problem, and the honest fix

Free tiers sleep. Render's free web service spins down after ~15 minutes idle, and
the next visitor waits 30–60 seconds. **That is not this app being slow** — it imports
in about 280 ms; the wait is container scheduling, and no amount of code tuning removes it.

Two things actually fix it:

**1. Pick a host that sleeps on a sane schedule.** Hugging Face Spaces (Docker SDK)
free CPU sleeps after **48 hours** of inactivity rather than 15 minutes, and needs no
credit card. For anything with occasional traffic it effectively never sleeps.

**2. Stop the visitor waiting on it.** The landing and guide pages carry no user data,
so they can be pre-rendered and served instantly from a CDN:

```bash
python tools/export_static.py --api https://your-backend-url
# deploy dist/ to Cloudflare Pages / Netlify / GitHub Pages
```

Those pages ping `/health` on load, so a sleeping container starts waking while the
visitor is still reading. By the time they click **Sign in**, it is warm. The perceived
cold start disappears even though the container still sleeps.

### Options, all without a credit card

| Host | Sleeps after | Card | Notes |
|---|---|---|---|
| **Hugging Face Spaces** (Docker) | **48 hours** | no | Best free option. Use the included `Dockerfile`; Spaces expects port 7860. |
| **Koyeb** | scale-to-zero | no | 512 MB RAM is tight with numpy + parselmouth — watch for OOM. |
| **Render** free | 15 minutes | no | Easiest deploy, worst cold start. Fine paired with the static export above. |
| **Cloudflare Pages** | never (static) | no | For `dist/` only. Instant, global. |
| **Neon** (Postgres) | scale-to-zero | no | Needed if the host has no persistent disk. |
| Oracle Cloud Always Free | never | **yes** | A real always-on VM, but it wants a card to verify. |
| Fly.io / Railway | — | **yes** | No longer free for new accounts. |

### Storage

Audio never touches the server disk — it is deleted after processing and the playback
copy lives in the visitor's browser. So the only persistent state is the SQLite file
of transcripts and metrics, measured in kilobytes per session. On a host with an
ephemeral disk, point `DATABASE_URL` at a free Neon Postgres instead. Every statement
uses `?` placeholders and `RETURNING` rather than `lastrowid`, so that is a driver
swap rather than a rewrite.

### Before you deploy

- Set `GROQ_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `SESSION_SECRET`
  as environment variables in the host's dashboard, never in a file.
- Set `ALLOW_DEV_LOGIN=false`.
- Add `https://your-domain/auth/callback` to the Google OAuth client, and publish the
  consent screen or only your test users can sign in.

## Layout

```
main.py                  FastAPI routes and screens
app/
  auth.py                Google sign-in and the session helpers
  config.py              .env loading, models, thresholds
  db.py                  parents, children, sessions (stdlib sqlite3, no ORM)
  groq_client.py         Whisper + LLM calls, 429 backoff with jitter
  metrics_text.py        pace, fillers, pauses, repetition, vocabulary
  metrics_audio.py       RMS energy, F0 via parselmouth, speech ratio
  baseline.py            per-child pitch/volume normalisation
  ideas.py               seven-dimension idea scoring, defensive JSON parsing
  feedback.py            chooses the praise and the one tip, then phrases them
  charts.py              inline SVG trend charts, no JS charting library
  pipeline.py            one recording in, one stored session out
  topics.py              age-band filtering and non-repeating rotation
data/
  topics.json            333 topics across three age bands
  top1000.txt            common-word list for the vocabulary metric
docs/
  LOGIN_PLAN.md          the design note the account model came from
templates/               Jinja2, one file per screen (_report.html is shared)
static/                  plain CSS, MediaRecorder capture, timers, and the IndexedDB
                         audio store that keeps playback on the user's own device
tools/
  build_topics.py        regenerates topics.json
  seed_demo.py           seeds demo sessions without spending API calls
tests/                   pytest suite for the deterministic layer
```

The frontend is Jinja2, plain CSS and two small vanilla JS files. No React, no build step,
no npm. JavaScript is used only where it has to be: microphone capture and the countdowns.
The trend charts are SVG generated in Python.

### One thing about the audio path

`MediaRecorder` produces WebM/Opus, which `parselmouth` cannot read and which would need
`ffmpeg` on the server to decode. Instead the browser decodes its own recording and converts
it to 16 kHz mono 16-bit WAV before upload, so the server needs no media tooling at all.
Automatic gain control is deliberately switched **off** during capture — AGC flattens
loudness, which would erase the exact volume differences the coach is trying to measure.

---

## Note on the model choice

The original plan specified `llama-3.3-70b-versatile`. **That model has been retired from
Groq** and returns a 404. The default is now `openai/gpt-oss-120b`, which is the strongest
instruction-following model currently on Groq's catalogue and supports JSON mode.

It is a *reasoning* model, so `reasoning_effort` is set to `low` — otherwise it spends the
entire token budget thinking and never emits the JSON. Both are configurable in `.env`:

```
LLM_MODEL=openai/gpt-oss-120b
LLM_REASONING_EFFORT=low
```

Transcription is unchanged: `whisper-large-v3` with `timestamp_granularities=["word"]`.
