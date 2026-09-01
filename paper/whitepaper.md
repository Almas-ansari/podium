# Measuring What Was Said, Not Only How It Sounded

### A hybrid deterministic and generative architecture for automated assessment of children's impromptu speech

**Almas Ansari** — almas.ansari@accenture.com

**Haresh Krishnan** — haresh.a.krishnan@accenture.com

---

## Abstract

We describe the architecture of a system that assesses short impromptu and
prepared speeches by children aged 6 to 14 and returns coaching feedback. The
contribution is architectural rather than algorithmic: every component uses
established methods, and the claim concerns their composition. The system
partitions assessment along a strict boundary. Delivery — speaking rate,
hesitation, disfluency, repetition, lexical range, fundamental frequency
variation and amplitude contour — is computed deterministically from the
transcript's word-level timestamps and from the audio signal. Content is
assessed by a large language model constrained to a seven-dimension rubric and
given the transcript only; it is instructed explicitly that it cannot hear the
audio. The corrective action returned to the child is selected by a fixed
priority ordering evaluated in code, not chosen by the model. Acoustic measures
are normalised within-subject against the speaker's own first three sessions and
are withheld entirely until that baseline exists. No numeric score is shown to
the child at any point.

**This paper reports no empirical results.** The system is implemented and
operational, but word error rate on the target population has not been measured,
agreement with human raters has not been computed, and no user study has been
conducted. Section 9 states an evaluation plan in the future tense. Section 10
states the limitations this imposes.

---

## 1. Problem statement

### 1.1 Target population

The system targets children aged 6 to 14 preparing for, or practising the skills
assessed in, school elocution, declamation, extempore and Just-A-Minute (JAM)
formats. The implementation partitions this range into three bands — `6-8`,
`9-11` and `12-14` — and the topic corpus is filtered by band. The corpus
contains 333 prompts distributed across those three bands, alongside a
1,046-token common-word list used for lexical rarity measurement.

Two roles are distinguished throughout the implementation. The *speaker* is the
child. The *account holder* is a parent or guardian, who is the party that
consents, and the party to whom numeric assessment is shown.

### 1.2 Three constraints

**Acoustic heterogeneity.** Fundamental frequency in this age range varies
substantially with developmental stage. A single fixed threshold applied to
pitch or amplitude will classify younger speakers differently from older ones for
reasons unrelated to speaking skill. Any absolute acoustic criterion therefore
encodes a confound between age and performance.

**ASR degradation on child speech.** Automatic speech recognition is trained
predominantly on adult speech. Children exhibit higher fundamental frequency,
different formant structure, greater articulatory variability and markedly more
disfluency. Accented child English compounds this. Every downstream content
judgement is conditioned on transcript quality, so transcription error is not an
isolated component risk but a systemic one. We have not measured this error rate
(Section 9.1).

**Behavioural sensitivity to negative feedback.** The system's objective is
practice volume: a child who records regularly improves, and a child who stops
recording does not. Assessment output that reduces the probability of a
subsequent session is counterproductive regardless of its accuracy. This is a
design premise, argued in Section 3.4 and Section 7.3 from reasoning rather than
from measurement within this work.

---

## 2. Related systems

### 2.1 Adult speech coaching

A mature category of consumer tools assesses adult presentation and interview
speech, typically reporting speaking rate, filler-word counts, and a composite
described as a confidence or delivery score. These systems generally assume a
speaker who has volunteered for evaluation, tolerates a numeric verdict, and
falls within adult acoustic norms.

### 2.2 Child pronunciation and literacy

Systems addressing children predominantly target the phonemic and lexical
levels: pronunciation accuracy, oral reading fluency, and decoding. The unit of
assessment is the word or phoneme, and the reference is a known target text. The
task addressed here has no reference text — the child is generating novel
discourse — so alignment-based scoring does not apply.

### 2.3 Clinical speech therapy

Clinical instruments assess articulation, fluency disorders and language
development against normative data, administered or supervised by a clinician.
The purpose is diagnostic. The present system makes no diagnostic claim and is
not a clinical instrument.

### 2.4 Why adult systems cannot be reskinned

Three specific obstacles, each corresponding to a constraint in Section 1.2.

First, **acoustic thresholds do not transfer**. A criterion calibrated on adult
fundamental frequency will misclassify a seven-year-old systematically rather
than randomly.

Second, **the scored construct is different**. Adult tools optimise delivery for
speakers who already reliably generate content. In the target population the
dominant structural failure is content-side — most visibly, exploring one idea
versus enumerating several and abandoning them. Section 6 describes the rubric
that follows from this.

Third, **the reporting contract is different**. An adult presented with 43/100
may treat it as actionable. The design premise in Section 1.2 holds that a child
may instead stop. This is not a skin-level difference; it changes what the system
is permitted to output, and therefore what it is worth computing.

---

## 3. Design principles

**3.1 Delivery is measured, never inferred.** A language model receives text. It
cannot hear the audio. Asking it how a speaker sounded produces fluent text
uncorrelated with the signal. All delivery quantities are therefore computed in
code from timestamps and samples.

**3.2 Determinism where a longitudinal claim is made.** The parent-facing
interface plots metrics across sessions. A trend line is only interpretable if
re-analysing the same recording yields the same value. Every quantity plotted
longitudinally is deterministic by construction.

**3.3 Within-subject acoustic normalisation.** Pitch and amplitude are
interpreted only relative to the same speaker's own prior sessions, and are
suppressed until that baseline exists.

**3.4 Bounded corrective load.** Exactly one corrective action is returned per
session, selected by a fixed ordering in code.

**3.5 Graceful degradation.** Content assessment is the only component that can
fail opaquely. Its failure path is explicit: the session degrades to
delivery-only feedback rather than emitting fabricated scores.

---

## 4. System architecture

The implementation is a single Python service (FastAPI) with server-rendered
templates. The modules below are as they exist in the repository; line counts are
given to indicate where complexity sits.

```
                        audio (16 kHz mono PCM, browser-encoded)
                                        |
                                        v
                        +-------------------------------+
                        |  pipeline.process()           |   131 lines
                        |  writes a scratch file,       |
                        |  deletes it in `finally`      |
                        +-------------------------------+
                                        |
              +-------------------------+-------------------------+
              |                                                   |
              v                                                   v
   +---------------------+                          +--------------------------+
   |  groq_client        |  144 lines               |  metrics_audio           | 181
   |  transcribe()       |                          |  parselmouth F0,         |
   |  whisper-large-v3   |                          |  numpy RMS, envelope     |
   |  verbose_json,      |                          +--------------------------+
   |  word + segment     |                                       |
   |  timestamps         |                                       v
   +---------------------+                          +--------------------------+
              |                                     |  baseline                | 134
              |  transcript + word timings          |  within-subject ratios,  |
              v                                     |  N = 3 sessions          |
   +---------------------+                          +--------------------------+
   |  metrics_text       |  242 lines                          |
   |  pace, fillers,     |                                     |
   |  pauses, repetition,|                                     |
   |  vocabulary,        |                                     |
   |  completion         |                                     |
   +---------------------+                                     |
              |                                                |
              |             +----------------------+           |
              +------------>|  ideas.score()       | 161       |
              |             |  7 dimensions, 1-5   |           |
              |             |  transcript only     |           |
              |             |  1 retry, then       |           |
              |             |  delivery-only       |           |
              |             +----------------------+           |
              |                        |                       |
              v                        v                       v
        +-----------------------------------------------------------+
        |  feedback.build()                                583 lines |
        |  choose_focus()  <- fixed FOCUS_ORDER, evaluated in code   |
        |  choose_win()    <- evidence selection, in code            |
        |  metric_block()  <- structured facts for the phrasing model|
        |  _write_lines()  <- model phrases only; template fallback  |
        +-----------------------------------------------------------+
                                        |
                                        v
                        +-------------------------------+
                        |  db.insert_session()          |   441 lines
                        |  transcript, word timings,    |
                        |  metrics, ideas, feedback     |
                        |  audio_path = NULL            |
                        +-------------------------------+
```

The ordering in `pipeline.py` is explicit and commented: transcript, then
deterministic delivery metrics, then baseline comparison, then content scoring,
then feedback synthesis, then persistence.

---

## 5. Deterministic delivery measurement

### 5.1 Transcription

Transcription uses Groq's hosted `whisper-large-v3` (configurable via
`WHISPER_MODEL`). The request sets `response_format="verbose_json"`,
`timestamp_granularities=["word", "segment"]`, `language="en"` and
`temperature=0.0`. Word-level timestamps are requested and are load-bearing: the
pause and rate metrics are derived from them. The client filters malformed word
entries rather than discarding the response, and returns an explicit `words` list
so that a caller can detect their absence rather than silently scoring an empty
sequence.

### 5.2 Temporal metrics

**Speaking rate.** Rate is computed over the *speaking span* — from the start
timestamp of the first word to the end timestamp of the last — not over the clip
duration. Where fewer than two words are returned, the clip duration is used as a
fallback. The token count is obtained by regular-expression tokenisation of the
transcript (`[a-z']+`), falling back to the word-timestamp count.

Bands are assigned by these thresholds, as written:

| Condition | Band | Flagged |
|---|---|---|
| `wpm < 90` | hesitant | yes |
| `90 ≤ wpm < 100` | slightly slow | no |
| `100 ≤ wpm ≤ 150` | typical | no |
| `150 < wpm ≤ 170` | slightly fast | no |
| `wpm > 170` | rushing | yes |

Only `hesitant` and `rushing` set the flag consumed by corrective selection.

**Hesitation pauses.** For each adjacent word pair the inter-word gap is
`start[n+1] − end[n]`. The gap is rounded to three decimal places *before*
comparison, because word timestamps arrive at 10 ms resolution and raw
floating-point subtraction turns a clean 0.70 s gap into 0.7000000000000002,
which would classify identical pauses inconsistently across runs. A gap strictly
greater than **0.7 s** is recorded as a hesitation.

Pause *distribution* is computed, not only pause count. The module returns:
total count; longest gap; count falling within the first **15 s** of the speaking
span; a three-way split of gaps into first, middle and final thirds of the span;
and the first forty individual gap positions and durations. Two derived
predicates follow: `weak_opening` when three or more gaps fall in the opening
window, and `went_blank` when the longest gap reaches **3.0 s**.

**Completion.** Coverage is `spoken_until / target_seconds`. `ran_out` is
asserted when coverage is below 0.6 *or* trailing silence after the final word
exceeds 5 s. `went_full_distance` requires coverage ≥ 0.9.

### 5.3 Disfluency

The filler lexicon is a nine-item tuple, exactly:

```
("um", "uh", "er", "like", "so", "basically", "actually", "matlab", "yaani")
```

The final two are Hindi discourse markers, included because the intended
deployment population code-switches. Matching is whole-token and
case-insensitive, performed after the same tokenisation used for rate. The module
returns raw count, per-minute rate over the speaking span, a per-token breakdown,
the modal filler, and a `heavy` predicate at ≥ 6 per minute.

Critically, the module also returns `reliable`, defined as `total > 0`. Whisper
decoding may normalise disfluencies away. A zero count is therefore treated as
weak evidence of absence rather than proof, and this propagates: the structured
block passed to the phrasing model states *"Fillers: none detected (the
transcriber may have dropped them — do not praise this)"* rather than reporting
zero. Corrective selection additionally requires `reliable` before it will flag
fillers. This is a mitigation, not a solution; see Section 10.3.

### 5.4 Repetition and lexical range

Both are implemented.

**Repetition** counts bigram and trigram types occurring twice or more. N-grams
composed entirely of a 32-item stopword set are excluded, so that function-word
sequences such as "and the" do not dominate. A rate is computed as
`Σ(count − 1) × 2 / total_tokens`. The `heavy` predicate fires at three or more
repeated trigram types, or a rate above 0.25.

**Lexical range** reports type-token ratio over the whole transcript, together
with a count of unique tokens absent from the shipped 1,046-word common list and
longer than three characters. Note that type-token ratio is length-dependent; no
length correction is applied (Section 10.6).

### 5.5 Acoustic measurement

Acoustic analysis exists and runs locally on the server; no audio is sent to any
third party for this stage. WAV decoding uses the standard library `wave` module
into NumPy arrays.

**Amplitude.** Root-mean-square energy is computed over 50 ms frames. Frames
below 15% of peak RMS are treated as silence and excluded. The module returns
mean RMS over speech frames, a scale-free coefficient of variation
(`std / mean`), and the percentage drop between the first two-thirds and the
final third of speech frames. `trails_off` is asserted at a drop of 25% or more.
A separate speech-to-silence ratio thresholds frames at half the median RMS.

**Fundamental frequency.** F0 is computed with **Praat** via the
`praat-parselmouth` binding, using `Sound.to_pitch()` with `pitch_floor=75.0` and
`pitch_ceiling=600.0`. Unvoiced frames (F0 = 0) are discarded. If fewer than ten
voiced frames survive, the module reports unavailability rather than a value. It
returns mean, standard deviation, minimum and maximum F0, and the voiced frame
count. Praat exceptions on very short or silent input are caught and reported as
unavailable.

The 600 Hz ceiling is a documented inconsistency in the implementation: the
source comment asserts that young children routinely exceed it, yet the ceiling
is set at that value, which would clip such speakers. This is recorded as a
divergence and as a limitation (Section 10.7).

### 5.6 Within-subject normalisation

The baseline module implements Principle 3.3. A speaker's baseline is the
arithmetic mean of the **first three** sessions (`BASELINE_SESSIONS = 3`) for
which the relevant quantity is available, taken oldest-first. Two quantities are
baselined: F0 **standard deviation** (as the proxy for expressive variation) and
**mean RMS**. Mean F0 is stored in the baseline structure but is not used for
comparison.

Current-session values are expressed as ratios to that baseline and mapped to
categories:

| Quantity | Ratio condition | Status |
|---|---|---|
| F0 std | ≤ 0.7 | monotone |
| F0 std | ≥ 1.3 | expressive |
| F0 std | otherwise | typical |
| Mean RMS | ≤ 0.7 | quieter |
| Mean RMS | ≥ 1.4 | louder |
| Mean RMS | otherwise | typical |

Before three qualifying sessions exist, `compare()` returns
`calibrating = True` with both statuses set to `calibrating` and both ratios
`None`, and **returns before computing any verdict**. The consequences are
enforced at two further points. The text passed to the phrasing model becomes a
single line — *"Pitch and volume: still calibrating (n/3 sessions) — do not
comment on these"* — and the corrective selector guards both acoustic candidates
behind `not calibrating`. An acoustic finding therefore cannot reach the child
before the baseline exists.

---

## 6. Content assessment

### 6.1 Rubric

The model receives the transcript, the topic, the mode and the age band. It is
instructed that the transcript is ASR output and to judge the thinking rather
than the transcription, and it is instructed explicitly: *"You must NOT comment
on voice, tone, pace, volume, confidence or nerves. You cannot hear the audio.
Those are measured separately."*

Seven dimensions are scored on an integer scale of **1 to 5**, anchored in the
prompt as 1 = absent, 3 = present but ordinary, 5 = strong for a child of this
age. The dimension names and definitions are as written in the prompt:

| Dimension | Definition as given to the model |
|---|---|
| `specificity` | concrete details, named people, places, numbers, moments, versus abstractions |
| `personal_stake` | did the child put themselves in it, an experience or an opinion they own |
| `reasoning` | claims backed with a reason ("because…"), versus asserted and dropped |
| `angle` | their own way into the topic, versus the most obvious take |
| `development` | one idea properly explored, versus several ideas touched and abandoned |
| `on_topic` | did they stay with the topic they were given |
| `structure` | a clear opening and a real ending, versus starting mid-thought and just stopping |

The model additionally returns four structured observations — `has_opening`,
`has_ending`, `distinct_points`, `used_example` — and three short free-text
fields: `main_idea`, `strongest_moment`, and `biggest_opening`. The last is used
by the feedback layer as raw material for an additive correction.

The rubric is **authored, not derived** from a corpus of judged speeches. Its
construct validity is unestablished (Section 10.2).

### 6.2 Mode-dependent weighting

The two modes are scored differently at three distinct points in the code.

**Weighted aggregate.** A weighted mean over the seven dimensions produces an
overall score, normalised to 0–100 as `(mean − 1) / 4 × 100`. Weights differ by
mode:

| Dimension | Prepared | Impromptu |
|---|---|---|
| specificity | 1.0 | 1.0 |
| personal_stake | 0.8 | 1.0 |
| reasoning | 1.0 | 0.8 |
| angle | 0.8 | 0.8 |
| development | 1.0 | **0.5** |
| on_topic | 1.0 | 1.0 |
| structure | 1.0 | **0.4** |

Development and structure are discounted in impromptu mode. The rationale
encoded here is that in prepared mode these represent preparation failures, while
in impromptu mode they are the ordinary cost of composing under time pressure.

**Corrective threshold.** The threshold at which thin development becomes
eligible as a corrective action is mode-dependent: `development ≤ 3` in prepared
mode, `≤ 2` in impromptu mode.

**Structure predicate.** In prepared mode, a missing ending alone makes structure
eligible. In impromptu mode, both a missing ending *and* a missing opening are
required.

This aggregate is never shown to the child. It appears only in the
parent-facing interface and in the stored record.

### 6.3 Robustness

The model is called with `temperature=0.0` and `response_format={"type":
"json_object"}`. Because the configured default model is a reasoning model
(`openai/gpt-oss-120b`), `reasoning_effort` is set to `low`; without it the model
consumes the token budget on reasoning and returns no document.

Parsing is defensive and layered. `_extract_json` first strips markdown fences,
attempts a direct parse, and on failure extracts the substring between the first
`{` and the last `}` and retries. `_normalise` clamps every dimension into
[1, 5], rejects the response outright if **any** dimension is missing or
non-numeric, bounds `distinct_points` to [0, 10], and truncates the free-text
fields.

On unparseable output the call is retried **exactly once**. If the second attempt
also fails to parse, the function returns `{"available": False}` and the session
proceeds with delivery-only feedback. Note an asymmetry: a *transport or API*
exception breaks the retry loop immediately rather than retrying, so the retry
budget applies to malformed documents, not to network failures. No default or
imputed scores are ever substituted.

---

## 7. Feedback synthesis

### 7.1 Division of labour

The selection of *what to say* is performed in code. The model performs only
*phrasing*.

`choose_focus()` evaluates nine boolean candidate conditions and returns the
first that holds under this fixed ordering:

```
ran_out → rushing → fillers → development → specifics
        → monotone → trailing_volume → structure → repetition
```

with a `keep_going` fallback when none holds. The ordering is a literal tuple in
the source and is evaluated by a `for` loop; **the model has no influence over
which corrective action is selected.** Ordering rationale is authored, reflecting
a judgement that a speaker who runs out of content cannot benefit from advice
about vocal variety. This ordering has not been empirically validated
(Section 10.4).

`choose_win()` selects the strength to praise from a ranked list of evidence-
backed candidates, preferring a quotation of something the child actually said
(`strongest_moment`) over generic categories. It then removes any candidate that
would contradict the selected correction — praising steady pace while correcting
rushing, praising low fillers while correcting fillers, and so on — via an
explicit conflict map.

`metric_block()` assembles the structured facts: age band, mode, topic,
transcript, duration against target, rate with band, filler summary or the
unreliability notice, pause count with opening-window count and longest gap, the
baseline-permitted acoustic lines, and the seven dimension scores with the three
free-text observations. The phrasing model receives this block *plus the
already-chosen* focus and win, and is instructed to write about those only.

If the phrasing call fails or returns unusable output, a deterministic
template-based fallback produces both sentences from the same selected focus and
win, and the stored record marks `source: "fallback"`. Feedback generation
therefore has no single point of failure that can block a session.

### 7.2 Single-action constraint

The phrasing prompt states: *"Exactly ONE thing to try next time. Never two.
Never a list."* The constraint is additionally enforced structurally — the
function returns a two-field object (`win`, `tip`), and the selection layer
supplies exactly one focus key.

The prompt further requires that corrections be phrased additively — what to add
next time — rather than as a verdict on what was deficient. Age-band-specific
style constraints are supplied, including sentence-length limits and, for the
youngest band, an explicit list of abstract vocabulary to avoid.

### 7.3 Score withholding

The phrasing prompt's first absolute rule is: *"NEVER give a score, mark, rating,
percentage, grade or any 'out of' number."* Counts of real events and durations
are permitted; evaluative numbers are not.

This is an assessment design decision rather than a presentation preference. The
system's objective function is practice volume, because improvement is
conditioned on repeated practice. A design that measures accurately while
suppressing the behaviour it exists to encourage has optimised the wrong
quantity. The full numeric record — every dimension score, the weighted
aggregate, all delivery metrics and the transcript — is computed, stored, and
exposed to the account holder. Nothing is discarded; the numbers are routed away
from the speaker.

We state plainly that the premise underlying this decision — that numeric
feedback suppresses practice frequency in this population — is asserted from
reasoning and is not measured within this work. It is the single most important
claim in the paper that an evaluation should test (Section 9.4).

---

## 8. Data protection

Each control below is stated as implemented or planned, according to what is
present in the source.

### 8.1 Implemented

**Consent capture.** Consent is stored per child, not per account, in two
columns on the `children` table: `consent_at` (ISO 8601 UTC timestamp) and
`consent_name` (the consenting adult's name, truncated to 120 characters).

**Consent enforcement.** The single request handler capable of initiating a
recording checks `child["consent_at"]` and returns HTTP 403 when it is absent,
before the uploaded bytes are read or forwarded anywhere.

**Audio deletion timing.** The uploaded audio is written to a scratch file
because the Praat binding reads from disk. `pipeline.process()` wraps the entire
analysis in `try` / `finally` and calls `unlink(missing_ok=True)` in the
`finally` clause, so deletion occurs on every path including every error path.
The session row is written with `audio_path = None`. No recording outlives the
request that produced it.

**What is retained server-side.** Per session: the full transcript text; the
complete word-level timestamp array; all computed delivery metrics; the content
scores; the generated feedback; mode, age band, topic, target duration and
measured duration. Per child: a first name, an age band, and the consent record.
**The transcript is retained in full and is a verbatim record of the child's
speech.** This is a substantive retention, and is stated here rather than
minimised.

**Playback copies.** The playback copy of the recording is held client-side in
IndexedDB in the family's own browser. It is per-device and is not synchronised.

**Deletion paths.** Two are implemented: `delete_child()` removes one child and
all dependent rows within an explicit transaction; `delete_all_for_parent()`
iterates children and then removes the account.

**Third-party scripts.** Verified by inspection of every served template and
static asset: there are no third-party script tags, no analytics, no advertising
SDK, and no external font or CDN reference. The only external URLs appearing in
markup are the authors' own profile links in the footer, plus the W3C SVG
namespace URI, which is an XML identifier and not a network fetch.

### 8.2 Third parties in the data path

Two, both server-side and both named on the consent screen.

**Groq** receives the audio bytes for transcription and the transcript for
content scoring. **Google** is the identity provider for the parent account and
receives no data about the child.

### 8.3 Not implemented

**Inference-provider retention terms are not configured in code.** No
zero-data-retention header, flag or account-level retention setting is set by the
application when calling the inference provider. We searched the source for any
such configuration and found none. Whatever retention policy applies is the
provider's account default, not a property this system asserts. Configuring and
verifying this is **planned, not implemented**, and no claim about the provider's
handling of transmitted audio or transcripts is made in this paper.

**Data protection legislation.** The consent mechanism was designed with India's
DPDP Act 2023 in mind, and the code comment records that intent. This paper makes
no claim of legal compliance; no assessment against the Act's requirements for
verifiable parental consent has been carried out.

---

## 9. Evaluation plan

**No evaluation has been performed. Nothing in this section is a result.** The
system is implemented and operational; its accuracy, agreement with human
judgement, and behavioural effects are all unmeasured. This section states what
we intend to do, in the future tense.

### 9.1 Transcription accuracy on the target population

We will collect recordings from children within the three age bands, speaking
freely for the durations the system supports, and will transcribe each by hand to
produce a reference. We will compute word error rate against the system's
transcripts, reporting per-band figures separately, since we expect degradation
to be strongest in the youngest band. We will additionally measure whether
disfluency tokens survive decoding, because the filler metric depends on it and
currently protects itself only by declining to assert absence (Section 5.3).

Because every content judgement is conditioned on transcript quality, this
measurement gates the interpretation of all others. Should error rates prove
high, the appropriate response may be to narrow the supported age range rather
than to adjust downstream components.

### 9.2 Agreement with human raters

We will recruit experienced elocution and debate judges, have them score a common
set of recordings against the seven-dimension rubric, and compute inter-rater
reliability among them before comparing the system to their consensus. Reporting
system–human agreement without first establishing human–human agreement would
make the comparison uninterpretable. We will report per-dimension agreement, as
we expect `on_topic` to be considerably more tractable than `angle`.

### 9.3 Test–retest determinism

We will re-analyse identical recordings across repeated runs and confirm that
every quantity plotted longitudinally is bit-identical, and that content scores
vary only within the bounds permitted by decoding at temperature zero. This
verifies Principle 3.2 as an implementation property.

### 9.4 Behavioural effect of score withholding

This tests the premise of Section 7.3 and is the study we consider most
important. We will compare practice frequency and session-completion rates
between the current design and a variant that exposes the numeric aggregate to
the child. The outcome measure is return rate over a fixed window, not
self-reported preference. We note that this design requires care with informed
consent, since one arm deliberately exposes children to a condition we
hypothesise to be discouraging.

### 9.5 Baseline sufficiency

We will test whether three sessions is adequate to characterise a speaker's
acoustic norm, by computing the stability of the baseline estimate as sessions
accumulate and determining the point at which additional sessions cease to move
it materially. `BASELINE_SESSIONS = 3` is currently an assumption.

### 9.6 Corrective ordering

We will test whether the authored priority ordering in Section 7.1 corresponds to
what coaches would prioritise for the same recordings, by presenting judges with
sessions and asking for their single highest-priority correction.

---

## 10. Limitations

**10.1 No empirical validation.** Nothing about this system's accuracy or effect
has been measured. Every performance claim that could be made is at present
unsupported. This is the governing limitation and conditions all others.

**10.2 The rubric is authored, not derived.** The seven dimensions were written
from reasoning about what distinguishes stronger from weaker speeches in this
population, not induced from a corpus of speeches with known judge scores. The
dimensions may not be mutually independent; `specificity` and `personal_stake`
plausibly correlate. The weightings are likewise authored. No factor analysis or
construct validation has been performed.

**10.3 Filler detection depends on ASR decoding behaviour.** Whisper may
normalise disfluencies out of its output. The system mitigates this by treating a
zero count as unreliable, propagating that caveat to the phrasing model, and
refusing to select fillers as a corrective action when the count is zero. The
mitigation prevents a false claim of fluency; it does **not** recover the
information. Under-reporting is therefore possible and its magnitude is unknown.

**10.4 The corrective ordering is asserted.** The ordering encodes a plausible
pedagogical claim but is not derived from measurement.

**10.5 English only; code-switching unhandled.** Transcription is requested with
`language="en"`. The filler lexicon includes two Hindi discourse markers, which
acknowledges that the population code-switches, but the system has no general
mechanism for handling mixed-language speech: content scoring, tokenisation,
lexical rarity and the common-word list are English-only. A child switching
languages mid-speech will be transcribed and assessed unpredictably.

**10.6 Lexical measures are length-sensitive.** Type-token ratio decreases with
transcript length by construction, so it is not comparable across sessions of
different durations. No moving-average or length-corrected variant is
implemented. The rarity count is likewise a raw count against a fixed 1,046-word
list, which is small and was assembled by the authors rather than drawn from a
frequency corpus.

**10.7 Acoustic parameters are partly inconsistent.** The Praat pitch ceiling is
set to 600 Hz while the accompanying source comment asserts that young children
routinely exceed it. Speakers above the ceiling will have F0 estimates clipped or
dropped, which affects precisely the youngest band the normalisation scheme
exists to protect.

**10.8 Single speaker only.** The system assumes exactly one speaker throughout
the recording. No diarisation is performed and none is present in the source.
Background speech, an adult prompting the child, or two children speaking will be
attributed to the single speaker without detection.

**10.9 Content assessment inherits transcription error.** The prompt instructs
the model to judge thinking rather than transcription, which is a mitigation of
presentation but not of information loss. Content lost or corrupted in
transcription cannot be assessed.

**10.10 Playback copies are per-device.** Because the playback recording is held
in browser storage, it is unavailable on other devices and is lost if site data
is cleared. This is a deliberate trade against server-side retention, and it is a
real functional limitation.

**10.11 No clinical claim.** The system is not a diagnostic instrument and its
output must not be read as evidence about speech or language development.

---

## 11. Conclusion

We have described the architecture of a system that assesses children's short
speeches and returns bounded coaching feedback. The design partitions assessment
by what each mechanism can actually determine: quantities recoverable from the
signal and its timestamps are computed deterministically in code, and only the
assessment of ideas — for which no deterministic method exists — is delegated to
a generative model, which is given the transcript alone and told explicitly that
it cannot hear the audio.

Three consequences follow from that partition. Longitudinal reporting becomes
defensible, because the plotted quantities are reproducible by construction.
Acoustic measures become interpretable across a developmentally heterogeneous
population, because they are expressed relative to each speaker's own prior
sessions and withheld before that baseline exists. And the corrective action
becomes auditable, because it is selected by a fixed ordering evaluated in code
rather than by a model whose selection criteria cannot be inspected.

We have deliberately separated what the system computes from what it shows the
child. The numeric record is complete and is available to the account holder; it
is withheld from the speaker on the argument that a system whose purpose is to
increase practice should not emit the signal most likely to end it.

The architecture is implemented and operational. It is not validated. We regard
the transcription accuracy measurement of Section 9.1 and the behavioural study
of Section 9.4 as the two results that would determine whether this design is
sound, and we report neither.

---

## References

The following are referenced as the established methods and instruments the
implementation composes. This is a systems paper; the citations describe
components, not evidence for claims about performance.

1. Boersma, P., & Weenink, D. *Praat: doing phonetics by computer.* Computer
   program. The autocorrelation-based pitch estimation used here is invoked
   through this implementation.
2. Jadoul, Y., Thompson, B., & de Boer, B. (2018). Introducing Parselmouth: A
   Python interface to Praat. *Journal of Phonetics*, 71, 1–15.
3. Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., & Sutskever, I.
   (2023). Robust Speech Recognition via Large-Scale Weak Supervision.
   *Proceedings of the 40th International Conference on Machine Learning.*
   (The `whisper-large-v3` checkpoint used here.)
4. Harris, C. R., et al. (2020). Array programming with NumPy. *Nature*, 585,
   357–362.
5. Templin, M. C. (1957). *Certain Language Skills in Children.* University of
   Minnesota Press. (Type-token ratio as a lexical diversity measure, and its
   known length dependence.)
6. Ministry of Electronics and Information Technology, Government of India
   (2023). *The Digital Personal Data Protection Act, 2023.* (The legislation
   the consent mechanism was designed with reference to; no compliance
   assessment is claimed.)
