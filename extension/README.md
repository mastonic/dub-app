# Doublage FR : extension Chrome (YouTube + X)

Regarde une vidéo YouTube ou X avec une voix française synchronisée. L'extension coupe le son
d'origine et joue le français phrase par phrase, en suivant pause, avance et retour.

Elle ne parle qu'à ton serveur local (`localhost:8000`) et n'est active que sur YouTube et X.

## 1. Lancer le serveur local (dans le terminal Linux)

```bash
cd ~/dub-app/dub-app/dub-app/backend && git pull
source .venv/bin/activate
pip install -r requirements.txt

export GROQ_API_KEY="..."           # obligatoire : transcription (https://console.groq.com/keys)
export ANTHROPIC_API_KEY="sk-ant-..."   # traduction Claude (sinon Google, plus lent)
export ANTHROPIC_WORKSPACE_ID="..."     # seulement si ta clé n'est pas rattachée à un workspace
# export LIVE_VOICE="fr-FR-VivienneMultilingualNeural"   # autre voix
# export LIVE_RATE="-5%"                                 # voix plus posée

python live_server.py
```

Laisse ce terminal ouvert pendant que tu regardes.

## 2. Installer l'extension

1. Dans Chrome, ouvre `chrome://extensions` et active **Mode développeur**.
2. Clique sur **Charger l'extension non empaquetée**.
3. Choisis le dossier `extension` (dans « Fichiers Linux » : `dub-app/dub-app/dub-app/extension`).

## 3. Utiliser

Ouvre une vidéo YouTube (page `/watch` ou `/shorts`) ou un post X, puis clique sur le bouton
**FR · Doubler** en bas à gauche. Le son d'origine reste actif 30 à 60 s pendant la préparation,
puis le français prend la main. Clique à nouveau pour arrêter.

## Limites

- La vidéo est préparée à l'avance, plus vite que la lecture : ce n'est pas du direct instantané.
- Pour un vrai direct, le français aura un retard de plusieurs secondes.
- Publicités YouTube : la voix se met en pause pendant les pubs.
- X : le bouton fonctionne sur la page d'un post (`/utilisateur/status/...`), pas dans le fil.
- Limite de l'API de transcription : environ 25 Mo d'audio, soit plus d'une heure de vidéo.
- Si l'extension ne joint pas le serveur, relance-le avec `HOST=0.0.0.0 python live_server.py`.
