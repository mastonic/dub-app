# Doublage FR : interface web + backend

```
dub-app/
├── backend/   FastAPI + ffmpeg + Whisper (Docker) -> Railway / Render / Fly.io / VPS
└── web/       Next.js -> Vercel
```

Vercel ne peut pas exécuter ffmpeg, Whisper ni yt-dlp : le traitement tourne sur le backend,
et le site Vercel sert d'interface (la clé API reste côté serveur Vercel).

## 1. Tester le backend en local

```bash
cd backend
pip install -r requirements.txt
export API_KEY="une_longue_cle_secrete"
export ANTHROPIC_API_KEY="ta_cle"      # optionnel (sinon traduction Google)
uvicorn server:app --port 8000
```

Test :
```bash
curl -X POST localhost:8000/jobs \
  -H "x-api-key: une_longue_cle_secrete" -H "content-type: application/json" \
  -d '{"url":"https://youtu.be/XXXX"}'
```

## 2. Déployer le backend (exemple Railway)

1. Pousse le dossier `backend/` sur GitHub (ou tout le projet, avec Root Directory = `backend`).
2. Railway > New Project > Deploy from GitHub : il détecte le `Dockerfile`.
3. Variables : `API_KEY`, `ANTHROPIC_API_KEY`, (optionnel) `WHISPER_MODEL=small`.
4. Génère le domaine public et note l'URL.

Prévois au moins 2 Go de RAM (Whisper `small`). Avec `WHISPER_MODEL=base`, 1 Go suffit.

## 3. Déployer le frontend sur Vercel

```bash
cd web
npm install
cp .env.example .env.local      # remplis BACKEND_URL et BACKEND_API_KEY
npm run dev                     # test local sur http://localhost:3000

npm i -g vercel
vercel                          # Root Directory = web
vercel env add BACKEND_URL
vercel env add BACKEND_API_KEY
vercel --prod
```

## Limites à connaître

- Les jobs sont gardés en mémoire et les fichiers 6 h : un redémarrage du backend les efface.
- Un seul job à la fois par défaut (`MAX_CONCURRENT`).
- Seuls les liens X/Twitter et YouTube sont acceptés.
- YouTube bloque parfois les IP de datacenter : si yt-dlp échoue, il faut des cookies
  (option `--cookies` de yt-dlp) ou un hébergement sur IP résidentielle / VPS.
- Respecte les droits d'auteur : ne double que des vidéos dont tu as le droit de réutiliser le contenu.
