"""
Backend FastAPI : reçoit un lien X/YouTube, lance dub_fr.py en tâche de fond,
expose le statut et la vidéo finale.

Variables d'environnement :
  API_KEY            clé partagée avec le frontend Vercel (obligatoire)
  ANTHROPIC_API_KEY  traduction Claude (sinon Google via deep-translator)
  WHISPER_MODEL      small par défaut
  MAX_CONCURRENT     nombre de jobs en parallèle (défaut 1)
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

API_KEY = os.environ.get("API_KEY", "")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/tmp/dub_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
RETENTION_SECONDS = 6 * 3600

ALLOWED_HOSTS = {
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}
VOICES = {"fr-FR-DeniseNeural", "fr-FR-HenriNeural", "fr-FR-VivienneMultilingualNeural",
          "fr-FR-RemyMultilingualNeural", "fr-FR-EloiseNeural"}

app = FastAPI(title="Doublage FR")
jobs: dict[str, dict] = {}
slots = threading.Semaphore(MAX_CONCURRENT)


def check_key(x_api_key: str = Header(default="")):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide")


class JobIn(BaseModel):
    url: str
    voice: str = "fr-FR-DeniseNeural"
    keep_original: float = 0.1


def validate_url(url: str):
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        raise HTTPException(400, "Seuls les liens X/Twitter et YouTube sont acceptés.")


def cleanup_old():
    now = time.time()
    for jid, job in list(jobs.items()):
        if now - job["created"] > RETENTION_SECONDS:
            shutil.rmtree(JOBS_DIR / jid, ignore_errors=True)
            jobs.pop(jid, None)


STEP_RE = re.compile(r"\[(\d)/5\]")


def worker(jid: str, body: JobIn):
    job = jobs[jid]
    job["status"] = "queued"
    with slots:
        job["status"] = "running"
        workdir = JOBS_DIR / jid
        output = workdir / "video_fr.mp4"
        cmd = [sys.executable, "dub_fr.py", body.url, "-o", str(output),
               "--workdir", str(workdir / "work"), "--voice", body.voice,
               "--whisper", WHISPER_MODEL, "--keep-original", str(body.keep_original)]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, cwd=Path(__file__).parent)
            tail = []
            for line in proc.stdout:
                print(f"[{jid}] {line}", end="", flush=True)
                tail = (tail + [line.rstrip()])[-15:]
                m = STEP_RE.search(line)
                if m:
                    job["step"] = int(m.group(1))
            proc.wait(timeout=60 * 60)
            if proc.returncode == 0 and output.exists():
                job["status"] = "done"
                shutil.rmtree(workdir / "work", ignore_errors=True)
            else:
                job["status"] = "error"
                rc = proc.returncode
                hint = ""
                if rc in (-9, 137):
                    hint = (" Arrêt par manque de mémoire probable : "
                            "utilise WHISPER_MODEL=tiny ou augmente la RAM.")
                job["error"] = (f"Le traitement s'est arrêté (code {rc}).{hint}\n"
                                + "\n".join(tail[-5:]))
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)


@app.post("/jobs", dependencies=[Depends(check_key)])
def create_job(body: JobIn):
    validate_url(body.url)
    if body.voice not in VOICES:
        raise HTTPException(400, "Voix inconnue.")
    if not 0 <= body.keep_original <= 0.5:
        raise HTTPException(400, "keep_original doit être entre 0 et 0.5.")
    cleanup_old()
    jid = uuid.uuid4().hex[:12]
    (JOBS_DIR / jid).mkdir(parents=True)
    jobs[jid] = {"status": "queued", "step": 0, "created": time.time(), "error": None}
    threading.Thread(target=worker, args=(jid, body), daemon=True).start()
    return {"id": jid}


@app.get("/jobs/{jid}", dependencies=[Depends(check_key)])
def get_job(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job introuvable")
    return {"id": jid, "status": job["status"], "step": job["step"], "error": job["error"]}


@app.get("/jobs/{jid}/video", dependencies=[Depends(check_key)])
def get_video(jid: str):
    job = jobs.get(jid)
    path = JOBS_DIR / jid / "video_fr.mp4"
    if not job or job["status"] != "done" or not path.exists():
        raise HTTPException(404, "Vidéo non disponible")
    return FileResponse(path, media_type="video/mp4", filename="video_fr.mp4")


@app.get("/health")
def health():
    return {"ok": True}
