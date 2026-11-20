// Speak with Aquila (window.Speak): a hands-free voice conversation with the
// study Aquila, from the Aquila page's composer and the home screen's ask box.
//
// Tap the mic and Aquila says hello, then listens. When you pause, Deepgram turns what you said into
// words (app/voice.py), they go in as an ordinary question (the same grounded
// Aquila, her answer and citations on screen), and the answer is read aloud a
// piece at a time, starting the moment it shows rather than when the stream
// ends. Then it listens again, until you tap Stop, stay quiet for a while, or
// leave the page. Refuge doesn't offer this: its call is Cognigy's.
//
// What keeps it from dropping: the mic level is read on a timer (animation
// frames stop when a phone dims its screen), what counts as speech is measured
// against the room's own noise each turn, the audio is woken before each turn
// (phones suspend it after playback), one failed request is tried again, and
// "Done" sends a turn by hand if the pause is never heard.
(() => {
  const NOTICE_KEY = "adullamSpeechNoticeSeen";
  const GREETED_KEY = "adullamSpeechGreeted";
  // What she says before the first turn, so a silent mic never leaves anyone
  // wondering what to do. The longer one the first time on a device.
  const GREETINGS = {
    first: "Hi, I'm Aquila. Ask me anything about the Bible, and pause when you're done. I'll answer on screen and read it to you, then listen for your next question.",
    again: "Hi, it's Aquila. What would you like to look at in the Bible?",
  };
  const TICK_MS = 50;
  const CALIBRATE_MS = 300;          // the start of each turn measures the room's noise
  const MIN_LEVEL = 0.006;           // the quietest level ever counted as speech (RMS, 0 to 1)
  const MAX_FLOOR = 0.015;           // a room this loud is treated as this loud, so a voice still stands out
  const NOISE_FACTOR = 2.5;          // speech is this much louder than the room
  const MIN_SPEECH_MS = 250;         // less than this is a cough or a click, not a question
  const SILENCE_MS = 1300;           // a pause this long ends what you're saying
  const WAIT_FOR_SPEECH_MS = 30000;  // this long with nothing said ends the session, so the mic is never left open
  const MAX_TURN_MS = 90000;
  // How long each piece read aloud may be. The first is a sentence or two, so
  // her voice comes within a moment of the answer; each after is longer and is
  // fetched while the one before plays. Deepgram reads up to 2,000 a request.
  const PIECE_SIZES = [160, 450, 1200];
  const SENTENCE = /[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g;
  const RETRY_MS = 700;
  // A silent clip played inside the first tap, so phones let the answer play later.
  const SILENCE_CLIP = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
  const MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const STOP = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>';
  const CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';

  const cave = () => window.Cave;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const toast = (text, tone = "info") => cave().toast(text, { tone });

  // The session while it runs: { stream, audio, context, analyser, ask, ui, button, greeting, cancelTurn, finishTurn, reading, skipped }.
  let session = null;
  let serverReady = null; // a promise: does this server offer Speak (a Deepgram key)?

  /** Whether Speak can be offered here: signed in, a browser that records, a server that's set up. */
  function available() {
    if (!cave().signedIn() || !navigator.mediaDevices || !window.MediaRecorder) return Promise.resolve(false);
    serverReady ??= cave().api("/me/voice/speech").then((r) => !!r.ready).catch(() => { serverReady = null; return false; });
    return serverReady;
  }

  function apiUrl(path) {
    const base = (document.getElementById("apiBase") || {}).value || location.origin;
    return `${base.trim().replace(/\/$/, "")}${path}`;
  }

  // A signed-in fetch that tries once more after a dropped connection or a
  // server error, and throws the server's own words (a 429 is a daily limit).
  async function voiceFetch(path, init) {
    for (let attempt = 1; ; attempt++) {
      let resp = null;
      try {
        resp = await fetch(apiUrl(path), { ...init, headers: { ...(await cave().authHeaders()), ...init.headers } });
      } catch {
        /* the connection dropped; tried again below */
      }
      if (resp && resp.ok) return resp;
      if ((!resp || resp.status >= 500) && attempt < 2) {
        await wait(RETRY_MS);
        continue;
      }
      const data = resp ? await resp.json().catch(() => ({})) : {};
      const err = new Error(typeof data.detail === "string" ? data.detail : "Voice isn't working just now. Check your connection.");
      err.status = resp ? resp.status : 0;
      throw err;
    }
  }

  // ---------------------------------------------------------------------
  // Listening
  // ---------------------------------------------------------------------
  // Records one turn. Resolves { blob } once the person pauses after speaking
  // (or taps Done), { silent: true } when nothing was said for a long while,
  // or { cancelled: true } when the session ended mid-turn.
  function recordTurn(s) {
    return new Promise((resolve) => {
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
      let recorder;
      try {
        recorder = new MediaRecorder(s.stream, type ? { mimeType: type } : undefined);
      } catch {
        return resolve({ failed: true });
      }
      const chunks = [];
      const samples = new Float32Array(s.analyser.fftSize);
      const began = performance.now();
      let last = began;
      let floor = 0;
      let calibration = 0;
      let speechMs = 0;
      let quietSince = began;
      let outcome = null;

      const finish = (result) => {
        outcome ??= result;
        clearInterval(timer);
        if (recorder.state === "recording") recorder.stop();
      };
      s.cancelTurn = () => finish({ cancelled: true });
      s.finishTurn = () => finish({ manual: true }); // Done: send what's there, heard or not

      const timer = setInterval(() => {
        s.analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const v of samples) sum += v * v;
        const level = Math.sqrt(sum / samples.length);
        const now = performance.now();
        const step = now - last;
        last = now;
        if (now - began < CALIBRATE_MS) {
          floor += level;
          calibration += 1;
          return;
        }
        if (calibration) {
          floor = Math.min(MAX_FLOOR, floor / calibration);
          calibration = 0;
        }
        const threshold = Math.max(MIN_LEVEL, floor * NOISE_FACTOR);
        s.ui.level(level / threshold);
        if (level > threshold) {
          speechMs += step;
          quietSince = now;
        } else if (speechMs === 0) {
          floor = Math.min(MAX_FLOOR, floor * 0.98 + level * 0.02); // follow the room while waiting
        }
        const heard = speechMs >= MIN_SPEECH_MS;
        if (heard && now - quietSince > SILENCE_MS) finish({ heard: true });
        else if (!heard && now - began > WAIT_FOR_SPEECH_MS) finish({ silent: true });
        else if (now - began > MAX_TURN_MS) finish({ heard });
      }, TICK_MS);

      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = () => {
        clearInterval(timer);
        s.ui.level(0);
        s.cancelTurn = s.finishTurn = null;
        const result = outcome || { cancelled: true };
        if (result.cancelled || result.silent || result.failed) return resolve(result);
        if (!result.heard && !result.manual) return resolve({ silent: true });
        resolve({ blob: new Blob(chunks, { type: (recorder.mimeType || type || "audio/webm").split(";")[0] }) });
      };
      recorder.start();
    });
  }

  async function transcribe(blob) {
    const resp = await voiceFetch("/me/voice/transcribe", { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
    return ((await resp.json()).text || "").trim();
  }

  // ---------------------------------------------------------------------
  // Reading the answer aloud
  // ---------------------------------------------------------------------
  // The answer in pieces Deepgram can read, cut between sentences and sized
  // by PIECE_SIZES. Paragraphs stay apart (a heading starts its own line), so
  // the server can still turn "## Context" into a sentence of its own.
  function pieces(text) {
    const out = [];
    let current = "";
    for (const para of text.split(/\n{2,}|\n(?=#)/).map((p) => p.trim()).filter(Boolean)) {
      (para.match(SENTENCE) || [para]).forEach((raw, i) => {
        const sentence = raw.trim();
        if (!sentence) return;
        const limit = PIECE_SIZES[Math.min(out.length, PIECE_SIZES.length - 1)];
        if (current && current.length + sentence.length + 2 > limit) {
          out.push(current);
          current = "";
        }
        current = current ? `${current}${i ? " " : "\n\n"}${sentence}` : sentence;
      });
    }
    if (current) out.push(current);
    return out;
  }

  async function audioFor(text) {
    const resp = await voiceFetch("/me/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    return URL.createObjectURL(await resp.blob());
  }

  // Plays one piece; resolves when it ends or the reading is stopped.
  function play(s, run, url) {
    return new Promise((resolve) => {
      run.interrupt = () => {
        s.audio.pause();
        resolve();
      };
      s.audio.onended = s.audio.onerror = () => resolve();
      s.audio.src = url;
      s.audio.play().catch(() => resolve());
    });
  }

  // Reads the whole answer, fetching each next piece while one plays, until
  // it ends or `run` is stopped (Skip, Stop, or a retried answer taking over).
  async function readAloud(s, text, run) {
    const live = () => session === s && !run.stopped;
    const parts = pieces(text);
    let next = parts.length ? audioFor(parts[0]) : null;
    for (let i = 0; next && live(); i++) {
      const url = await next;
      next = i + 1 < parts.length ? audioFor(parts[i + 1]) : null;
      next?.catch(() => {}); // a failure is met when it's awaited
      if (live()) await play(s, run, url);
      URL.revokeObjectURL(url);
    }
    next?.then(URL.revokeObjectURL, () => {});
  }

  // Starts `work(run)` as the session's reading, taking over from any under
  // way. `s.reading.done` settles when the latest reading ends.
  function begin(s, work) {
    s.reading?.stop();
    const run = { stopped: false };
    run.stop = () => {
      run.stopped = true;
      run.interrupt?.();
    };
    run.done = work(run);
    run.done.catch(() => {}); // a failure is met when it's awaited
    s.reading = run;
    return run;
  }

  // Reads an answer. When the grounding check sends Aquila back for a better
  // one, the new answer is read instead.
  const read = (s, text) => begin(s, (run) => readAloud(s, text, run));

  // The greeting's audio, fetched once a page and kept, since its words never change.
  const greetings = new Map();
  function greetingAudio(text) {
    if (!greetings.has(text)) greetings.set(text, audioFor(text).catch((err) => (greetings.delete(text), Promise.reject(err))));
    return greetings.get(text);
  }

  // Which greeting this is: the longer one until she has met them on this device.
  function greetingText() {
    let met = false;
    try {
      met = localStorage.getItem(GREETED_KEY) === "1";
      localStorage.setItem(GREETED_KEY, "1");
    } catch {
      /* private window: the short one would leave them guessing */
    }
    return met ? GREETINGS.again : GREETINGS.first;
  }

  // Says hello before the first turn. A greeting that fails is skipped quietly:
  // the bar still says she's listening.
  async function greet(s) {
    s.ui.show("greeting");
    const run = begin(s, async (r) => {
      const url = await greetingAudio(s.greeting);
      if (session === s && !r.stopped) await play(s, r, url);
    });
    await run.done.catch(() => {});
    s.reading = null;
  }

  // Skip: this answer goes unread, even if a retried one arrives after it.
  function skip() {
    if (!session) return;
    session.skipped = true;
    session.reading?.stop();
  }

  // ---------------------------------------------------------------------
  // The status bar: one line above the box while a session runs
  // ---------------------------------------------------------------------
  function bar(mount) {
    const { el } = cave();
    const dot = el("span", { class: "voice-dot", "aria-hidden": "true" });
    const state = el("span", { class: "voice-state" });
    const act = el("button", { class: "act", type: "button" });
    const close = el("button", { class: "voice-close", type: "button", "aria-label": "Stop speaking", title: "Stop speaking", html: CLOSE, onclick: () => stop() });
    const node = el("div", { class: "voice-bar", role: "status", "aria-live": "polite" }, [dot, state, act, close]);
    mount.prepend(node);
    const words = {
      listening: ["Listening. Pause when you're done.", "Done"],
      hearing: ["Hearing you...", null],
      greeting: ["Aquila is saying hello", "Skip"],
      thinking: ["Aquila is answering...", null],
      speaking: ["Aquila is speaking", "Skip"],
    };
    return {
      show(step) {
        const [text, label] = words[step];
        node.dataset.step = step;
        state.textContent = text;
        act.hidden = !label;
        act.textContent = label || "";
        act.onclick = step === "listening" ? () => session?.finishTurn?.() : skip;
      },
      level(ratio) {
        node.style.setProperty("--level", Math.max(0, Math.min(1, (ratio - 0.6) / 2)).toFixed(2));
      },
      remove: () => node.remove(),
    };
  }

  // ---------------------------------------------------------------------
  // The session
  // ---------------------------------------------------------------------
  // Before the first time: where the voice goes, said plainly.
  function notice() {
    let seen = false;
    try {
      seen = localStorage.getItem(NOTICE_KEY) === "1";
    } catch {
      /* private window: ask each time */
    }
    if (seen) return Promise.resolve(true);
    const { el, overlay } = cave();
    return new Promise((resolve) => {
      let answered = false;
      const answer = (yes) => {
        answered = true;
        if (yes) {
          try {
            localStorage.setItem(NOTICE_KEY, "1");
          } catch {
            /* fine */
          }
        }
        close();
        resolve(yes);
      };
      const close = overlay(el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "speechTitle" }, [
        el("h3", { id: "speechTitle", text: "Speak with Aquila" }),
        el("p", { class: "sheet-lede", text: "Ask out loud, and pause when you're done. Aquila answers on screen and reads it aloud, then listens again until you tap Stop." }),
        el("p", { text: "What you say goes to Deepgram to become words, and her answers go there to be read aloud. Deepgram is asked not to keep your voice. Your questions and her answers are kept with your conversations, like typed ones." }),
        el("div", { class: "sheet-actions" }, [
          el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Not now", onclick: () => answer(false) }),
          el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Start speaking", onclick: () => answer(true) }),
        ]),
      ]), { onClose: () => !answered && resolve(false) });
    });
  }

  async function loop(s) {
    const live = () => session === s;
    // A failed request is said and the session listens again; a daily limit,
    // or a second failure in a row, ends it. Returns whether it ended.
    let failures = 0;
    const failed = (err) => {
      failures += 1;
      if (err.status === 429 || failures >= 2) {
        stop(err.message, err.status === 429 ? "info" : "error");
        return true;
      }
      toast(err.message, "error");
      return false;
    };
    await greet(s);
    while (live()) {
      s.ui.show("listening");
      if (s.context.state !== "running") await s.context.resume().catch(() => {});
      const turn = await recordTurn(s);
      if (!live() || turn.cancelled) return;
      if (turn.failed) return stop("This browser couldn't record. You can keep typing.", "error");
      if (turn.silent) return stop("Stopped listening after a quiet while. Tap the mic to talk again.");
      s.ui.show("hearing");
      let text;
      try {
        text = await transcribe(turn.blob);
      } catch (err) {
        if (!live() || failed(err)) return;
        continue;
      }
      if (!live()) return;
      if (!text) {
        toast("I didn't catch that. Try again?");
        continue;
      }
      s.ui.show("thinking");
      s.skipped = false;
      s.reading = null;
      // Reading starts as soon as the answer is on screen, while the page
      // still waits on the grounding check and the follow-up questions.
      const startReading = (draft) => {
        if (!live() || s.skipped) return;
        s.ui.show("speaking");
        read(s, draft);
      };
      const answer = await s.ask(text, startReading);
      if (!live()) return;
      if (!answer) return stop(); // the page already says why
      failures = 0;
      if (!s.reading) startReading(answer);
      try {
        await s.reading?.done;
      } catch (err) {
        if (!live() || failed(err)) return;
      }
    }
  }

  /**
   * Starts a session, from inside the tap that asked for it (phones only let
   * audio start there). `mount` is where the status bar goes, `ask(text,
   * onAnswer)` asks the question, calls `onAnswer(text)` the moment the
   * answer shows, and resolves the answer's text (null when it failed),
   * and `button` is the mic that started it, shown pressed while it runs.
   */
  async function start({ mount, ask, button }) {
    if (session) return stop();
    const audio = new Audio(SILENCE_CLIP);
    audio.play().catch(() => {});
    const context = new (window.AudioContext || window.webkitAudioContext)();
    context.resume().catch(() => {});
    if (!(await notice())) return context.close().catch(() => {});
    // Fetched while the browser asks for the mic, so her hello comes straight after.
    const greeting = greetingText();
    greetingAudio(greeting).catch(() => {});
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch {
      context.close().catch(() => {});
      return toast("Allow the microphone to speak with Aquila.", "error");
    }
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const s = { stream, audio, context, analyser, ask, button, greeting, ui: bar(mount) };
    session = s;
    stream.getAudioTracks().forEach((t) => t.addEventListener("ended", () => session === s && stop("The microphone stopped. Tap the mic to talk again.")));
    pressed(button, true);
    loop(s);
  }

  /** Ends the session: the mic is released, any reading stops, the bar goes. */
  function stop(note, tone = "info") {
    const s = session;
    if (!s) return;
    session = null;
    s.cancelTurn?.();
    s.reading?.stop();
    s.audio.pause();
    s.stream.getTracks().forEach((t) => t.stop());
    s.context.close().catch(() => {});
    s.ui.remove();
    pressed(s.button, false);
    if (note) toast(note, tone);
  }

  function pressed(button, on) {
    if (!button) return;
    button.setAttribute("aria-pressed", String(on));
    button.innerHTML = on ? STOP : MIC;
    button.setAttribute("aria-label", on ? "Stop speaking" : "Speak with Aquila");
  }

  // A mic left open in a hidden tab is never what someone wants.
  document.addEventListener("visibilitychange", () => document.hidden && stop());

  window.Speak = { available, start, stop, active: () => !!session, MIC };
})();
