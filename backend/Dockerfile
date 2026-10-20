FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# Image légère : pas de Whisper local (transcription via GROQ_API_KEY)
RUN grep -vi faster-whisper requirements.txt > req-cloud.txt \
    && pip install --no-cache-dir -r req-cloud.txt

COPY dub_fr.py server.py ./

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
