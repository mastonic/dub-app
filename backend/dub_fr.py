#!/usr/bin/env python3
"""
dub_fr.py - Doublage automatique en français oral d'une vidéo X (Twitter) ou YouTube.

Pipeline :
  1. yt-dlp         -> télécharge la vidéo
  2. faster-whisper -> transcrit la voix d'origine (avec timestamps)
  3. Claude API     -> traduit en français oral naturel (ou Google via --translator google)
  4. edge-tts       -> génère la voix française (gratuit, voix neuronales Microsoft)
  5. ffmpeg/pydub   -> cale les phrases, baisse la voix d'origine, remonte la vidéo

Usage :
  python dub_fr.py "https://x.com/user/status/123456789"
  python dub_fr.py "https://youtu.be/XXXX" --voice fr-FR-HenriNeural --keep-original 0.12
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ---------------------------------------------------------------- 1. Téléchargement
def download(url: str, workdir: Path) -> Path:
    print("[1/5] Téléchargement de la vidéo...")
    target = workdir / "source.mp4"
    cmd = [
        "yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b", "--merge-output-format", "mp4",
        "--no-playlist", "-o", str(workdir / "source.%(ext)s"),
    ]
    # YouTube exige un runtime JavaScript (node) pour résoudre ses signatures.
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    # Cookies optionnels (contenu d'un cookies.txt au format Netscape) contre le blocage anti-bot.
    cookies = os.environ.get("YT_COOKIES", "").strip()
    if cookies:
        cfile = workdir / "cookies.txt"
        cfile.write_text(cookies + "\n", encoding="utf-8")
        cmd += ["--cookies", str(cfile)]
    proc = subprocess.run(cmd + [url])
    if proc.returncode != 0 or not target.exists():
        raise SystemExit(
            "Téléchargement impossible. Si c'est un lien YouTube : YouTube bloque souvent "
            "les serveurs (vérifie la ligne ERROR plus haut dans les logs). "
            "Essaie un lien X, ou configure YT_COOKIES."
        )
    return target


# ---------------------------------------------------------------- 2. Transcription
LANG_CODES = {
    "english": "en", "french": "fr", "spanish": "es", "german": "de", "italian": "it",
    "portuguese": "pt", "arabic": "ar", "russian": "ru", "chinese": "zh-CN",
    "japanese": "ja", "korean": "ko", "dutch": "nl", "turkish": "tr", "hindi": "hi",
}


def transcribe_groq(wav: Path, workdir: Path):
    """Transcription via l'API Groq (Whisper hébergé) : aucune charge mémoire locale."""
    import httpx
    mp3 = workdir / "asr.mp3"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
         "-ac", "1", "-ar", "16000", "-b:a", "32k", str(mp3)])
    if mp3.stat().st_size > 24 * 1024 * 1024:
        raise SystemExit("Vidéo trop longue pour l'API de transcription (limite ~25 Mo d'audio).")
    model = os.environ.get("GROQ_MODEL", "whisper-large-v3-turbo")
    print(f"[2/5] Transcription (Groq {model})...")
    with open(mp3, "rb") as f:
        r = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            files={"file": ("asr.mp3", f, "audio/mpeg")},
            data={"model": model, "response_format": "verbose_json",
                  "timestamp_granularities[]": "segment"},
            timeout=300,
        )
    if r.status_code != 200:
        raise SystemExit(f"Transcription Groq échouée ({r.status_code}) : {r.text[:200]}")
    j = r.json()
    segments = [
        {"start": float(x["start"]), "end": float(x["end"]), "text": x["text"].strip()}
        for x in j.get("segments", []) if x.get("text", "").strip()
    ]
    raw = str(j.get("language", "")).lower()
    lang = LANG_CODES.get(raw, raw if len(raw) == 2 else "auto")
    print(f"      Langue détectée : {lang} | {len(segments)} segments")
    return segments, lang


def transcribe(video: Path, workdir: Path, model_size: str):
    wav = workdir / "original.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    if os.environ.get("GROQ_API_KEY"):
        return transcribe_groq(wav, workdir)
    print(f"[2/5] Transcription (Whisper '{model_size}')...")
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, compute_type="int8")
    segs, info = model.transcribe(str(wav), vad_filter=True)
    segments = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segs if s.text.strip()
    ]
    print(f"      Langue détectée : {info.language} | {len(segments)} segments")
    return segments, info.language


# ---------------------------------------------------------------- 3. Traduction
def translate_claude(texts, model="claude-sonnet-5-5"):
    import anthropic
    # Clé non rattachée à un workspace : ajouter ANTHROPIC_WORKSPACE_ID.
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    client = anthropic.Anthropic(
        default_headers={"anthropic-workspace-id": ws} if ws else None
    )
    out = []
    for i in range(0, len(texts), 40):
        chunk = texts[i:i + 40]
        prompt = (
            "Traduis chaque phrase suivante en français oral, naturel et fluide, "
            "comme quelqu'un qui parle (pas de style écrit). Reste concis : la "
            "traduction doit pouvoir être prononcée dans le même temps que l'original. "
            "Réponds UNIQUEMENT par un tableau JSON de chaînes, de même longueur "
            f"({len(chunk)} éléments), dans le même ordre.\n\n"
            + json.dumps(chunk, ensure_ascii=False)
        )
        for attempt in range(3):
            msg = client.messages.create(
                model=model, max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text
            m = re.search(r"\[.*\]", raw, re.S)
            try:
                arr = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                arr = None
            if arr and len(arr) == len(chunk):
                out.extend(str(x) for x in arr)
                break
        else:
            raise SystemExit("Traduction Claude : réponse invalide après 3 essais.")
    return out


def translate_google(texts, src):
    import time
    from deep_translator import GoogleTranslator
    tr = GoogleTranslator(source=src or "auto", target="fr")
    out = []
    for t in texts:
        for attempt in range(6):
            try:
                out.append(tr.translate(t) or t)
                break
            except Exception:  # TooManyRequests, réseau...
                time.sleep(2 * (attempt + 1))
        else:
            raise SystemExit(
                "Traduction Google bloquée (trop de requêtes). "
                "Définis ANTHROPIC_API_KEY pour utiliser Claude à la place."
            )
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------- 4. Voix française
async def tts_all(items, voice, rate, workdir: Path):
    import edge_tts
    paths = []
    for idx, text in enumerate(items):
        p = workdir / f"tts_{idx:04d}.mp3"
        await edge_tts.Communicate(text, voice, rate=rate).save(str(p))
        paths.append(p)
    return paths


def speed_up(src: Path, factor: float) -> Path:
    dst = src.with_name(src.stem + "_fast.mp3")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-filter:a", f"atempo={factor:.3f}", str(dst)])
    return dst


# ---------------------------------------------------------------- 5. Assemblage
def assemble(video: Path, workdir: Path, segments, fr_texts, tts_paths,
             keep_original: float, max_speed: float, output: Path):
    print("[5/5] Assemblage audio + vidéo...")
    from pydub import AudioSegment

    total_ms = int(duration(video) * 1000) + 500
    voice_track = AudioSegment.silent(duration=total_ms)
    cursor = 0.0  # secondes : évite que deux phrases se chevauchent

    for i, seg in enumerate(segments):
        clip_path = tts_paths[i]
        d = duration(clip_path)
        next_start = segments[i + 1]["start"] if i + 1 < len(segments) else seg["end"] + 3
        slot = max(next_start - max(seg["start"], cursor), 0.3)
        if d > slot:
            factor = min(d / slot, max_speed)
            if factor > 1.02:
                clip_path = speed_up(clip_path, factor)
                d = duration(clip_path)
        start = max(seg["start"], cursor)
        clip = AudioSegment.from_file(clip_path)
        voice_track = voice_track.overlay(clip, position=int(start * 1000))
        cursor = start + d + 0.05

    if keep_original > 0:
        orig = AudioSegment.from_file(workdir / "original.wav")
        gain_db = 20 * __import__("math").log10(keep_original)
        orig = orig.apply_gain(gain_db)
        voice_track = voice_track.overlay(orig)

    dub = workdir / "dub.wav"
    voice_track.export(dub, format="wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(dub),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", str(output)])


# ---------------------------------------------------------------- Main
def main():
    ap = argparse.ArgumentParser(description="Doublage FR d'une vidéo X/YouTube")
    ap.add_argument("url", help="Lien de la vidéo (X/Twitter, YouTube, etc.)")
    ap.add_argument("-o", "--output", default="video_fr.mp4", help="Fichier de sortie")
    ap.add_argument("--voice", default="fr-FR-DeniseNeural",
                    help="Voix edge-tts (ex: fr-FR-HenriNeural, fr-FR-VivienneMultilingualNeural)")
    ap.add_argument("--rate", default="+0%", help="Débit de la voix, ex: +10%%")
    ap.add_argument("--whisper", default="small",
                    help="Taille Whisper : tiny, base, small, medium, large-v3")
    ap.add_argument("--translator", choices=["claude", "google"], default=None,
                    help="Défaut : claude si ANTHROPIC_API_KEY existe, sinon google")
    ap.add_argument("--keep-original", type=float, default=0.10,
                    help="Volume de la voix d'origine en fond (0 = coupée, 0.1 = 10%%)")
    ap.add_argument("--max-speed", type=float, default=1.5,
                    help="Accélération max de la voix FR pour tenir dans le temps")
    ap.add_argument("--workdir", default="work_dub", help="Dossier temporaire")
    args = ap.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(exist_ok=True)

    video = download(args.url, workdir)
    segments, lang = transcribe(video, workdir, args.whisper)
    if not segments:
        raise SystemExit("Aucune parole détectée dans la vidéo.")

    translator = args.translator or ("claude" if os.getenv("ANTHROPIC_API_KEY") else "google")
    print(f"[3/5] Traduction vers le français ({translator})...")
    texts = [s["text"] for s in segments]
    if lang == "fr":
        print("      La vidéo est déjà en français, rien à traduire.")
        fr_texts = texts
    elif translator == "claude":
        fr_texts = translate_claude(texts)
    else:
        fr_texts = translate_google(texts, lang)

    (workdir / "transcript_fr.json").write_text(
        json.dumps([{**s, "fr": t} for s, t in zip(segments, fr_texts)],
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[4/5] Génération de la voix ({args.voice})...")
    tts_paths = asyncio.run(tts_all(fr_texts, args.voice, args.rate, workdir))

    assemble(video, workdir, segments, fr_texts, tts_paths,
             args.keep_original, args.max_speed, Path(args.output))
    print(f"\nTerminé : {args.output}")
    print(f"Transcript FR : {workdir / 'transcript_fr.json'}")


if __name__ == "__main__":
    main()
