// Doublage FR : joue une voix française synchronisée avec la vidéo de la page.
(() => {
  if (window.__frDubLoaded) return;
  window.__frDubLoaded = true;

  const POLL_MS = 1500;     // interrogation du serveur
  const TICK_MS = 100;      // synchronisation avec la vidéo
  const PREFETCH = 6;       // clips téléchargés à l'avance
  const MAX_LAG = 4;        // au-delà (en s), on saute une phrase en retard
  const log = (...a) => console.debug("[FR]", ...a);

  let st = null;            // session en cours (null = inactif)

  // ------------------------------------------------------------------ interface
  const btn = document.createElement("button");
  btn.id = "fr-dub-btn";
  Object.assign(btn.style, {
    position: "fixed", left: "14px", bottom: "14px", zIndex: "2147483647",
    padding: "8px 14px", border: "0", borderRadius: "999px", cursor: "pointer",
    background: "#1d4ed8", color: "#fff", font: "600 13px system-ui, sans-serif",
    boxShadow: "0 2px 10px rgba(0,0,0,.4)",
  });
  const toast = document.createElement("div");
  Object.assign(toast.style, {
    position: "fixed", left: "14px", bottom: "56px", zIndex: "2147483647", maxWidth: "320px",
    padding: "8px 12px", borderRadius: "10px", background: "#111827", color: "#fff",
    font: "13px system-ui, sans-serif", display: "none", boxShadow: "0 2px 10px rgba(0,0,0,.4)",
  });
  document.documentElement.append(btn, toast);

  let toastTimer = null;
  function flash(text, ms = 7000) {
    toast.textContent = text;
    toast.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.style.display = "none"), ms);
  }
  function label(text, color = "#1d4ed8") {
    btn.textContent = text;
    btn.style.background = color;
  }
  label("FR · Doubler");

  function updateLabel() {
    const s = st;
    if (!s) return label("FR · Doubler");
    if (!s.live) {
      const stage = { download: "téléchargement", transcribe: "transcription", dub: "voix" }[s.stage] || "préparation";
      return label(`FR · ${stage}…`, "#b45309");
    }
    const prog = s.total ? ` ${Math.min(100, Math.round((s.done / s.total) * 100))} %` : "";
    label(s.finished ? "FR · actif ✓ (stop)" : `FR · actif${prog} (stop)`, "#15803d");
  }

  // ------------------------------------------------------------------ cible
  function currentTarget() {
    const u = new URL(location.href);
    const host = u.hostname.replace(/^www\./, "").replace(/^m\./, "");
    if (host === "youtube.com") {
      const v = u.searchParams.get("v");
      if (u.pathname === "/watch" && v) return `https://www.youtube.com/watch?v=${v}`;
      const m = u.pathname.match(/^\/shorts\/([\w-]+)/);
      return m ? `https://www.youtube.com/shorts/${m[1]}` : null;
    }
    if (host === "x.com" || host === "twitter.com") {
      const m = u.pathname.match(/^\/([^/]+)\/status\/(\d+)/);
      return m ? `https://x.com/${m[1]}/status/${m[2]}` : null;
    }
    return null;
  }

  function pickVideo() {
    let best = null, bestArea = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
      const h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
      if (w * h > bestArea) { best = v; bestArea = w * h; }
    }
    return best;
  }

  const adShowing = () => !!document.querySelector(".html5-video-player.ad-showing");

  function bg(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (r) => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(r || { ok: false, error: "Pas de réponse" });
        });
      } catch (e) {
        resolve({ ok: false, error: "Extension rechargée : recharge la page." });
      }
    });
  }

  // ------------------------------------------------------------------ audio
  function stopAudio(s) {
    s.gen++;                                   // annule les chargements en cours
    if (s.src && s.src !== "loading") {
      try { s.src.onended = null; s.src.stop(); } catch (_) { /* déjà arrêté */ }
    }
    s.src = null;
  }

  function getBuffer(s, i) {
    const clip = s.clips[i];
    if (!clip) return Promise.resolve(null);
    if (!s.buffers.has(i)) {
      const p = bg({ type: "clip", id: s.jobId, n: clip.n }).then(async (r) => {
        if (!r.ok) return null;
        const bin = atob(r.b64);
        const bytes = new Uint8Array(bin.length);
        for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
        try { return await s.ctx.decodeAudioData(bytes.buffer); } catch (_) { return null; }
      });
      s.buffers.set(i, p);
    }
    return s.buffers.get(i);
  }

  function playClip(s, i) {
    const gen = s.gen;
    s.src = "loading";                          // verrou : un seul clip à la fois
    getBuffer(s, i).then((buf) => {
      if (st !== s || s.gen !== gen) return;
      if (!buf) { s.src = null; s.next = i + 1; return; }
      const src = s.ctx.createBufferSource();
      src.buffer = buf;
      src.playbackRate.value = Math.min(2, Math.max(0.5, s.video.playbackRate || 1));
      src.connect(s.ctx.destination);
      src.onended = () => { if (s.src === src) s.src = null; };
      s.src = src;
      s.next = i + 1;
      src.start();
      log("play", s.clips[i].n, "clip.start=", s.clips[i].start, "video.t=", +s.video.currentTime.toFixed(2));
    });
  }

  // Première phrase qui commence maintenant ou plus tard : on n'entre pas au milieu d'une phrase.
  const firstIndexAt = (s, t) => s.clips.findIndex((c) => c.start > t - 0.5);

  function resync(s) {
    stopAudio(s);
    const t = s.video.currentTime;
    const i = firstIndexAt(s, t);
    s.next = i === -1 ? s.clips.length : i;
    s.lastT = t;
    log("resync", "t=", +t.toFixed(2), "next=", s.next);
  }

  function engage(s) {
    if (st !== s || s.live) return;
    s.live = true;
    s.prevMuted = s.video.muted;
    s.video.muted = true;
    resync(s);
    log("engage");
    updateLabel();
  }

  // ------------------------------------------------------------------ boucle de synchro
  function tick() {
    const s = st;
    if (!s) return;
    const v = s.video;
    if (currentTarget() !== s.url) return stop("Autre vidéo : doublage arrêté.");
    if (!v.isConnected) return stop("Vidéo remplacée : relance le doublage.");

    // premier clip prêt → on prend la main (le son d'origine reste actif avant)
    if (!s.live) {
      // on attend que les clips proches de la position actuelle soient téléchargés et décodés
      if (s.clips.length) {
        const t0 = v.currentTime;
        const i = firstIndexAt(s, t0);
        if (i !== -1 && s.engaging !== i) {
          s.engaging = i;
          Promise.all([getBuffer(s, i), getBuffer(s, i + 1)]).then(([b]) => {
            if (st !== s || s.live) return;
            if (b) engage(s); else s.engaging = false;     // échec : on réessaiera
          });
        }
      }
      return;
    }

    const t = v.currentTime;
    if (adShowing() || v.paused || v.readyState < 2) {
      if (s.ctx.state === "running") { s.ctx.suspend(); log("suspend"); }
      s.lastT = t;
      return;
    }
    if (s.ctx.state === "suspended") { s.ctx.resume(); log("resume"); }
    if (Math.abs(t - s.lastT) > 1.5) resync(s);   // saut dans la vidéo
    s.lastT = t;
    if (!v.muted) v.muted = true;

    for (let j = s.next; j < Math.min(s.next + PREFETCH, s.clips.length); j++) getBuffer(s, j);
    if (s.src) return;

    let c = s.clips[s.next];
    while (c && c.start < t - MAX_LAG) { log("skip", c.n); c = s.clips[++s.next]; }
    if (!c || c.start > t + 0.05) return;
    playClip(s, s.next);
  }

  async function poll() {
    const s = st;
    if (!s || !s.jobId || s.pollBusy) return;
    s.pollBusy = true;
    try {
      const r = await bg({ type: "status", id: s.jobId, after: s.clips.length });
      if (st !== s) return;
      if (!r.ok) {
        if (++s.errCount > 5) fail(r.error);
        return;
      }
      s.errCount = 0;
      const d = r.data;
      s.stage = d.stage; s.total = d.total; s.done = d.done;
      if (d.clips && d.clips.length) s.clips.push(...d.clips);
      if (d.status === "error") return fail(d.error);
      if (d.status === "french") return stop("Cette vidéo est déjà en français.");
      if (d.status === "done") { s.finished = true; clearInterval(s.polling); s.polling = null; }
      updateLabel();
    } finally {
      s.pollBusy = false;
    }
  }

  // ------------------------------------------------------------------ cycle de vie
  async function start() {
    const url = currentTarget();
    if (!url) return flash("Ouvre d'abord une vidéo (page YouTube /watch ou /shorts, ou un post X).");
    const video = pickVideo();
    if (!video) return flash("Aucune vidéo trouvée sur cette page.");
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume().catch(() => {});
    const s = (st = {
      url, video, ctx, jobId: null, clips: [], next: 0, buffers: new Map(), src: null,
      gen: 0, live: false, engaging: false, finished: false, errCount: 0, pollBusy: false,
      stage: "", total: 0, done: 0, lastT: video.currentTime, prevMuted: video.muted,
    });
    s.onSeek = () => { if (st === s && s.live) resync(s); };
    video.addEventListener("seeking", s.onSeek);
    label("FR · connexion…", "#b45309");
    const r = await bg({ type: "start", url });
    if (st !== s) return;
    if (!r.ok) return fail(r.error);
    s.jobId = r.id;
    flash("Préparation du français… la voix démarre dans 30 à 60 s, le son d'origine reste actif en attendant.", 9000);
    s.polling = setInterval(poll, POLL_MS);
    s.tick = setInterval(tick, TICK_MS);
    poll();
  }

  function stop(message) {
    const s = st;
    if (!s) return;
    st = null;
    clearInterval(s.polling);
    clearInterval(s.tick);
    stopAudio(s);
    s.video.removeEventListener("seeking", s.onSeek);
    try { s.ctx.close(); } catch (_) { /* déjà fermé */ }
    if (s.live) s.video.muted = s.prevMuted;
    label("FR · Doubler");
    if (message) flash(message);
  }

  function fail(error) {
    stop();
    flash(error || "Erreur inconnue", 12000);
  }

  btn.addEventListener("click", () => (st ? stop() : start()));
})();
