/* Loads a session's recording from this browser's storage into the player. */
(function () {
  "use strict";

  const mount = document.getElementById("playback");
  if (!mount || !window.AudioStore) return;

  const sessionId = mount.dataset.sessionId;
  const player = mount.querySelector("audio");
  const status = mount.querySelector(".playback-status");

  function say(message) {
    if (status) status.textContent = message;
  }

  window.AudioStore.load(sessionId)
    .then(function (record) {
      if (!record || !record.blob) {
        say("This recording is not on this device. Recordings are stored in the browser "
            + "they were made in, so they do not follow you to another computer.");
        if (player) player.remove();
        return;
      }
      const url = URL.createObjectURL(record.blob);
      player.src = url;
      player.hidden = false;
      say("Stored on this device only. Never uploaded for keeps.");
      player.addEventListener("error", function () {
        say("This recording could not be played back.");
      });
    })
    .catch(function () {
      say("Recordings could not be read from this browser's storage.");
      if (player) player.remove();
    });
})();
