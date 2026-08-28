/* Recordings live in this browser, not on the server.
 *
 * The audio still passes through the server to be transcribed - Groq needs the
 * bytes - but it is deleted the moment processing finishes. What is kept for
 * playback is the original Opus blob MediaRecorder produced, held here in
 * IndexedDB on the family's own device.
 *
 * Consequence to be honest about in the UI: recordings are per-device. Clearing
 * browser data removes them, and they do not follow you to another machine.
 */
(function () {
  "use strict";

  const DB_NAME = "thinkspeak";  // kept: renaming this would orphan saved recordings
  const DB_VERSION = 1;
  const STORE = "recordings";

  function open() {
    return new Promise(function (resolve, reject) {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = function () {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "id" });
        }
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  function run(mode, work) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        const tx = db.transaction(STORE, mode);
        const store = tx.objectStore(STORE);
        let result;
        try {
          result = work(store);
        } catch (err) {
          reject(err);
          return;
        }
        tx.oncomplete = function () {
          db.close();
          // An IDBRequest's result is legitimately undefined for a miss, a delete
          // or a clear, so unwrap by type rather than by truthiness - otherwise
          // those cases resolve with the request object itself.
          resolve(result instanceof IDBRequest ? result.result : result);
        };
        tx.onerror = function () { db.close(); reject(tx.error); };
        tx.onabort = function () { db.close(); reject(tx.error); };
      });
    });
  }

  const AudioStore = {
    /* Ask the browser not to evict these under disk pressure. Best effort:
       it can still say no, and Safari is stricter than Chrome. */
    requestPersistence: function () {
      if (navigator.storage && navigator.storage.persist) {
        return navigator.storage.persisted()
          .then(function (already) { return already || navigator.storage.persist(); })
          .catch(function () { return false; });
      }
      return Promise.resolve(false);
    },

    save: function (sessionId, blob, meta) {
      const record = Object.assign(
        { id: Number(sessionId), blob: blob, mime: blob.type || "audio/webm",
          savedAt: new Date().toISOString() },
        meta || {}
      );
      return run("readwrite", function (store) { store.put(record); });
    },

    load: function (sessionId) {
      return run("readonly", function (store) { return store.get(Number(sessionId)); });
    },

    remove: function (sessionId) {
      return run("readwrite", function (store) { store.delete(Number(sessionId)); });
    },

    /* Used by the delete-everything button: the server can only clear its own
       side, so the browser has to clear this. */
    clear: function () {
      return run("readwrite", function (store) { store.clear(); });
    },

    usage: function () {
      if (navigator.storage && navigator.storage.estimate) {
        return navigator.storage.estimate().catch(function () { return {}; });
      }
      return Promise.resolve({});
    }
  };

  window.AudioStore = AudioStore;
})();
