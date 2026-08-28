/* Microphone capture for the speaking screen.
 *
 * Captures with MediaRecorder, then converts to 16 kHz mono 16-bit WAV in the
 * browser before upload. The server needs plain PCM: the pitch and energy
 * analysis reads the waveform directly, and shipping WAV means the server
 * needs no ffmpeg to decode anything.
 *
 * Automatic gain control is switched off on purpose. AGC flattens loudness,
 * which would erase the very volume differences the coach is trying to measure.
 */
(function () {
  "use strict";

  const cfg = window.SPEAK_CONFIG;
  const el = {
    ring: document.getElementById("ring"),
    label: document.getElementById("ringLabel"),
    start: document.getElementById("startBtn"),
    stop: document.getElementById("stopBtn"),
    status: document.getElementById("status"),
    levels: document.getElementById("levels"),
    error: document.getElementById("error"),
    idle: document.getElementById("idleState"),
    live: document.getElementById("liveState"),
    busy: document.getElementById("busyState"),
  };

  let media = null, recorder = null, chunks = [], timer = null;
  let audioCtx = null, analyser = null, rafId = null, startedAt = 0;

  function fail(message) {
    el.error.textContent = message;
    el.error.classList.remove("hidden");
  }

  function show(state) {
    el.idle.classList.toggle("hidden", state !== "idle");
    el.live.classList.toggle("hidden", state !== "live");
    el.busy.classList.toggle("hidden", state !== "busy");
  }

  /* --- level meter ------------------------------------------------- */

  function meter(stream) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
    const source = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const buf = new Uint8Array(analyser.frequencyBinCount);
    const bars = el.levels.querySelectorAll("i");

    (function draw() {
      analyser.getByteFrequencyData(buf);
      const step = Math.floor(buf.length / bars.length);
      bars.forEach(function (bar, i) {
        let sum = 0;
        for (let j = i * step; j < (i + 1) * step; j++) sum += buf[j];
        const level = Math.min(1, (sum / step) / 110);
        bar.style.height = (18 + level * 82) + "%";
        bar.style.opacity = String(0.35 + level * 0.65);
      });
      rafId = requestAnimationFrame(draw);
    })();
  }

  /* --- WAV conversion ---------------------------------------------- */

  async function toWav(blob) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const decodeCtx = new Ctx();
    const decoded = await decodeCtx.decodeAudioData(await blob.arrayBuffer());
    decodeCtx.close();

    const targetRate = 16000;
    const frames = Math.ceil(decoded.duration * targetRate);
    const OfflineCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const offline = new OfflineCtx(1, frames, targetRate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();

    return encodeWav(rendered.getChannelData(0), targetRate);
  }

  function encodeWav(samples, rate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const text = (offset, str) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };

    text(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    text(8, "WAVEfmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);         // PCM
    view.setUint16(22, 1, true);         // mono
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);  // byte rate
    view.setUint16(32, 2, true);         // block align
    view.setUint16(34, 16, true);        // bits per sample
    text(36, "data");
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  /* --- recording lifecycle ------------------------------------------ */

  async function begin() {
    el.error.classList.add("hidden");
    el.start.disabled = true;

    try {
      media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false
        }
      });
    } catch (err) {
      el.start.disabled = false;
      fail("We could not reach the microphone. Please allow microphone access and try again.");
      return;
    }

    window.countIn(3, function () {
      show("live");
      meter(media);

      chunks = [];
      recorder = new MediaRecorder(media);
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = finish;
      recorder.start();
      startedAt = Date.now();

      timer = window.Countdown(el.ring, cfg.seconds, {
        onDone: function () { stop(); }
      });
      timer.start();
    });
  }

  function stop() {
    if (!recorder || recorder.state === "inactive") return;
    if (timer) timer.stop();
    if (rafId) cancelAnimationFrame(rafId);
    el.stop.disabled = true;
    recorder.stop();
    media.getTracks().forEach((t) => t.stop());
    if (audioCtx) audioCtx.close();
    show("busy");
  }

  async function finish() {
    const elapsed = (Date.now() - startedAt) / 1000;
    const original = new Blob(chunks, { type: chunks[0] ? chunks[0].type : "audio/webm" });
    if (elapsed < 3) {
      show("idle");
      el.start.disabled = false;
      fail("That was too short to give feedback on. Try speaking for a bit longer.");
      return;
    }

    let wav;
    try {
      wav = await toWav(original);
    } catch (err) {
      show("idle");
      el.start.disabled = false;
      fail("We could not read that recording. Please try once more.");
      return;
    }

    const form = new FormData();
    form.append("audio", wav, "speech.wav");
    form.append("topic_id", cfg.topicId);
    form.append("seconds", cfg.seconds);

    try {
      const res = await fetch("/api/session", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));

      if (res.ok && data.redirect) {
        // Keep the compact Opus original on this device. The server has already
        // discarded its copy by now, so this is the only surviving recording.
        const match = /\/feedback\/(\d+)/.exec(data.redirect);
        if (match && window.AudioStore) {
          try {
            await window.AudioStore.requestPersistence();
            await window.AudioStore.save(match[1], original, { duration: elapsed });
          } catch (err) {
            // Storage full or blocked: the session itself is fine, only playback is lost.
            console.warn("could not store the recording locally", err);
          }
        }
        window.location.href = data.redirect;
        return;
      }
      if (data.redirect) {
        window.location.href = data.redirect;
        return;
      }
      show("idle");
      el.start.disabled = false;
      fail(data.error || "Something went wrong. Please try again.");
    } catch (err) {
      show("idle");
      el.start.disabled = false;
      fail("We could not reach the server. Check your connection and try again.");
    }
  }

  el.start.addEventListener("click", begin);
  el.stop.addEventListener("click", stop);
})();
