"""
Serveur LOCAL de doublage progressif, utilisé par l'extension Chrome « Doublage FR ».

Pour une vidéo YouTube / X :
  1. télécharge l'audio seul (rapide)
  2. transcrit avec l'API Groq (obligatoire : GROQ_API_KEY)
  3. traduit par lots (Claude si ANTHROPIC_API_KEY, sinon Google)
  4. génère la voix française en parallèle (edge-tts) et cale chaque phrase dans son créneau
Les phrases sont disponibles au fur et à mesure : l'extension commence à jouer le français
après le premier lot, puis la voix reste en avance sur la vidéo.

Lancement :  python live_server.py        (127.0.0.1:8000)
Variables :  GROQ_API_KEY, ANTHROPIC_API_KEY, ANTHROPIC_WORKSPACE_ID (si besoin),
             LIVE_VOICE (défaut fr-FR-DeniseNeural), LIVE_RATE (défaut +0%),
             HOST, PORT, LIVE_DIR
"""
import asyncio
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import dub_fr

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
JOBS_DIR = Path(os.environ.get("LIVE_DIR", "live_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_VOICE = os.environ.get("LIVE_VOICE", "fr-FR-DeniseNeural")
RATE = os.environ.get("LIVE_RATE", "+0%")

MAX_SPEED = 1.5        # accélération max de la voix pour tenir dans le créneau
FIRST_BATCH = 8        # petit premier lot : la voix démarre plus vite
BATCH = 20
TTS_CONCURRENCY = 4
KEEP_SECONDS = 24 * 3600

ALLOWED_HOSTS = {
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}
VOICE_RE = re.compile(r"^fr-[A-Z]{2}-[A-Za-z]+Neural$")

app = FastAPI(title="Doublage FR local")
jobs: dict[str, dict] = {}
by_key: dict[str, str] = {}


def guard(request: Request, x_fr_dub: str = Header(default="")):
    """Seule l'extension peut appeler le serveur (en-tête perso + hôte local)."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host not in ("localhost", "127.0.0.1"):
        raise HTTPException(403, "Hôte refusé")
    if x_fr_dub != "1":
        raise HTTPException(403, "Appel refusé")


class DubIn(BaseModel):
    url: str
    voice: str | None = None


def validate_url(url: str):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in ALLOWED_HOSTS or u.username:
        raise HTTPException(400, "Seuls les liens YouTube et X sont acceptés.")


def cleanup_old():
    now = time.time()
    for jid, job in list(jobs.items()):
        if now - job["created"] > KEEP_SECONDS:
            shutil.rmtree(JOBS_DIR / jid, ignore_errors=True)
            jobs.pop(jid, None)
            for k, v in list(by_key.items()):
                if v == jid:
                    by_key.pop(k, None)


async def tts_parallel(texts, voice, rate, wd: Path, offset: int):
    import edge_tts
    sem = asyncio.Semaphore(TTS_CONCURRENCY)

    async def one(k, text):
        clean = re.sub(r"\s+", " ", text or "").strip()
        if not re.search(r"\w", clean):      # ♪, ..., [musique] : rien à lire
            return None
        p = wd / f"clip_{offset + k:05d}.mp3"
        async with sem:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(clean, voice, rate=rate).save(str(p))
                    if p.exists() and p.stat().st_size > 0:
                        return p
                except Exception:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None

    return await asyncio.gather(*[one(k, t) for k, t in enumerate(texts)])


def translate(texts, lang):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return dub_fr.translate_claude(texts)
    return dub_fr.translate_google(texts, lang)


def worker(jid: str, url: str, voice: str):
    job = jobs[jid]
    wd = JOBS_DIR / jid
    wd.mkdir(parents=True, exist_ok=True)
    try:
        if not os.environ.get("GROQ_API_KEY"):
            raise SystemExit("GROQ_API_KEY manquante : le mode extension a besoin de l'API Groq.")
        job["stage"] = "download"
        wav = dub_fr.download_audio(url, wd)
        job["stage"] = "transcribe"
        segments, lang = dub_fr.transcribe_groq(wav, wd)
        job["lang"] = lang
        if not segments:
            raise SystemExit("Aucune parole détectée dans cette vidéo.")
        if lang == "fr":
            job["status"] = "french"
            job["stage"] = "done"
            return
        job["total"] = len(segments)
        job["stage"] = "dub"
        i, size = 0, FIRST_BATCH
        while i < len(segments):
            chunk = segments[i:i + size]
            texts = translate([s["text"] for s in chunk], lang)
            paths = asyncio.run(tts_parallel(texts, voice, RATE, wd, i))
            for k, (seg, path) in enumerate(zip(chunk, paths)):
                if path is None:
                    continue
                idx = i + k
                nxt = segments[idx + 1]["start"] if idx + 1 < len(segments) else seg["end"] + 3
                slot = max(nxt - seg["start"], 0.4)
                dur = dub_fr.duration(path)
                if dur > slot:
                    factor = min(dur / slot, MAX_SPEED)
                    if factor > 1.03:
                        path = dub_fr.speed_up(path, factor)
                        dur = dub_fr.duration(path)
                job["clips"].append({
                    "n": len(job["clips"]), "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3), "dur": round(dur, 3), "file": str(path),
                })
            i += size
            size = BATCH
            job["done"] = min(i, len(segments))
        job["status"] = "done"
        job["stage"] = "done"
    except BaseException as e:  # noqa: BLE001  (SystemExit inclus)
        job["status"] = "error"
        job["error"] = (str(e) or e.__class__.__name__)[:300]


@app.get("/health")
def health(_: None = Depends(guard)):
    return {"ok": True, "groq": bool(os.environ.get("GROQ_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/dub")
def create(body: DubIn, _: None = Depends(guard)):
    validate_url(body.url)
    voice = body.voice or DEFAULT_VOICE
    if not VOICE_RE.match(voice):
        raise HTTPException(400, "Voix inconnue.")
    cleanup_old()
    key = f"{body.url}|{voice}"
    old = by_key.get(key)
    if old and old in jobs and jobs[old]["status"] != "error":
        return {"id": old}
    jid = uuid.uuid4().hex[:12]
    jobs[jid] = {"status": "running", "stage": "queued", "lang": None, "total": 0, "done": 0,
                 "error": None, "clips": [], "created": time.time()}
    by_key[key] = jid
    threading.Thread(target=worker, args=(jid, body.url, voice), daemon=True).start()
    return {"id": jid}


@app.get("/dub/{jid}")
def status(jid: str, after: int = 0, _: None = Depends(guard)):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job introuvable")
    clips = [{k: c[k] for k in ("n", "start", "end", "dur")} for c in job["clips"][max(after, 0):]]
    return {"status": job["status"], "stage": job["stage"], "lang": job["lang"],
            "total": job["total"], "done": job["done"], "error": job["error"], "clips": clips}


@app.get("/clip/{jid}/{n}")
def clip(jid: str, n: int, _: None = Depends(guard)):
    job = jobs.get(jid)
    if not job or n < 0 or n >= len(job["clips"]):
        raise HTTPException(404, "Clip introuvable")
    return FileResponse(job["clips"][n]["file"], media_type="audio/mpeg")


if __name__ == "__main__":
    import uvicorn
    print(f"Serveur de doublage sur http://{HOST}:{PORT}  (Ctrl+C pour arrêter)")
    if not os.environ.get("GROQ_API_KEY"):
        print("ATTENTION : GROQ_API_KEY n'est pas définie, le doublage échouera.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
