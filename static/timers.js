/* Countdown ring shared by the prep and speaking screens. */
(function () {
  "use strict";

  const R = 118;
  const CIRC = 2 * Math.PI * R;

  function format(total) {
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m > 0 ? m + ":" + String(s).padStart(2, "0") : String(s);
  }

  window.Countdown = function (root, totalSeconds, opts) {
    opts = opts || {};
    const fill = root.querySelector(".ring-fill");
    const face = root.querySelector(".ring-time");
    let remaining = totalSeconds;
    let handle = null;

    fill.style.strokeDasharray = CIRC.toFixed(1);
    fill.style.strokeDashoffset = "0";

    function paint() {
      const done = (totalSeconds - remaining) / totalSeconds;
      fill.style.strokeDashoffset = (CIRC * done).toFixed(1);
      face.textContent = format(Math.max(remaining, 0));
      root.classList.toggle("is-low", remaining <= Math.min(10, totalSeconds * 0.2));
      if (opts.onTick) opts.onTick(remaining);
    }

    function tick() {
      remaining -= 1;
      paint();
      if (remaining <= 0) {
        stop();
        if (opts.onDone) opts.onDone();
      }
    }

    function start() {
      paint();
      handle = setInterval(tick, 1000);
    }

    function stop() {
      if (handle) clearInterval(handle);
      handle = null;
    }

    paint();
    return { start, stop, remaining: () => remaining, elapsed: () => totalSeconds - remaining };
  };

  /* 3-2-1 overlay before recording starts. */
  window.countIn = function (from, done) {
    const overlay = document.createElement("div");
    overlay.className = "countin";
    const num = document.createElement("div");
    num.className = "countin-num";
    overlay.appendChild(num);
    document.body.appendChild(overlay);

    let n = from;
    function show() {
      if (n === 0) {
        overlay.remove();
        done();
        return;
      }
      num.textContent = n;
      num.style.animation = "none";
      void num.offsetWidth;
      num.style.animation = "";
      n -= 1;
      setTimeout(show, 850);
    }
    show();
  };
})();
