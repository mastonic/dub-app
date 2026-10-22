// Relais entre la page (YouTube / X) et le serveur local de doublage.
// Les appels partent d'ici pour ne pas être bloqués par les règles de sécurité des sites.
const BASE = "http://localhost:8000";
const HEADERS = { "x-fr-dub": "1" };

async function api(path, init = {}) {
  return fetch(BASE + path, { ...init, headers: { ...HEADERS, ...(init.headers || {}) } });
}

function toBase64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

chrome.runtime.onMessage.addListener((msg, _sender, send) => {
  (async () => {
    try {
      if (msg.type === "start") {
        const r = await api("/dub", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ url: msg.url }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) return send({ ok: false, error: j.detail || "Erreur " + r.status });
        return send({ ok: true, id: j.id });
      }
      if (msg.type === "status") {
        const r = await api(`/dub/${encodeURIComponent(msg.id)}?after=${msg.after | 0}`);
        const j = await r.json().catch(() => ({}));
        if (!r.ok) return send({ ok: false, error: j.detail || "Erreur " + r.status });
        return send({ ok: true, data: j });
      }
      if (msg.type === "clip") {
        const r = await api(`/clip/${encodeURIComponent(msg.id)}/${msg.n | 0}`);
        if (!r.ok) return send({ ok: false, error: "Clip " + r.status });
        const bytes = new Uint8Array(await r.arrayBuffer());
        return send({ ok: true, b64: toBase64(bytes) });
      }
      send({ ok: false, error: "Message inconnu" });
    } catch (e) {
      send({
        ok: false,
        error: "Serveur local injoignable : lance « python live_server.py » dans le terminal.",
      });
    }
  })();
  return true; // réponse asynchrone
});
