"use client";

import { useEffect, useRef, useState } from "react";

const STEPS = [
  "Téléchargement de la vidéo",
  "Transcription de la voix",
  "Traduction en français",
  "Génération de la voix française",
  "Assemblage audio + vidéo",
];

const VOICES = [
  { id: "fr-FR-DeniseNeural", label: "Denise (femme)" },
  { id: "fr-FR-HenriNeural", label: "Henri (homme)" },
  { id: "fr-FR-VivienneMultilingualNeural", label: "Vivienne (femme, multilingue)" },
  { id: "fr-FR-RemyMultilingualNeural", label: "Rémy (homme, multilingue)" },
  { id: "fr-FR-EloiseNeural", label: "Éloïse (voix jeune)" },
];

type Job = { id: string; status: string; step: number; error: string | null };

export default function Home() {
  const [url, setUrl] = useState("");
  const [voice, setVoice] = useState(VOICES[0].id);
  const [keep, setKeep] = useState(0.1);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const poll = async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Erreur");
        setJob(data);
        if (data.status === "done" || data.status === "error") {
          if (timer.current) clearInterval(timer.current);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erreur réseau");
        if (timer.current) clearInterval(timer.current);
      }
    };
    poll();
    timer.current = setInterval(poll, 3000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [jobId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setJob(null);
    setJobId(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: url.trim(), voice, keep_original: keep }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Erreur");
      setJobId(data.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setSubmitting(false);
    }
  }

  const running = !!job && (job.status === "queued" || job.status === "running");
  const done = job?.status === "done";

  return (
    <main>
      <h1>Doublage en français</h1>
      <p className="sub">Colle un lien X ou YouTube, récupère la vidéo avec une voix française.</p>

      <form className="card" onSubmit={submit}>
        <label htmlFor="url">Lien de la vidéo</label>
        <input
          id="url"
          type="url"
          required
          placeholder="https://x.com/... ou https://youtu.be/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <label htmlFor="voice">Voix</label>
        <select id="voice" value={voice} onChange={(e) => setVoice(e.target.value)}>
          {VOICES.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <label htmlFor="keep">Voix d'origine en fond : {Math.round(keep * 100)} %</label>
        <input
          id="keep"
          type="range"
          min={0}
          max={0.5}
          step={0.05}
          value={keep}
          onChange={(e) => setKeep(parseFloat(e.target.value))}
        />
        <button type="submit" disabled={submitting || running}>
          {submitting ? "Envoi..." : running ? "Traitement en cours..." : "Doubler en français"}
        </button>
      </form>

      {error && <div className="card err">{error}</div>}

      {job && (
        <div className="card">
          <ul className="steps">
            {STEPS.map((label, i) => {
              const n = i + 1;
              const isDone = done || job.step > n;
              const isActive = !done && job.status !== "error" && job.step === n;
              return (
                <li key={label} className={isDone ? "done" : isActive ? "active" : ""}>
                  <span>{isDone ? "✓" : isActive ? "…" : "○"}</span>
                  {label}
                </li>
              );
            })}
          </ul>
          {job.status === "queued" && <p className="sub">En file d'attente...</p>}
          {job.status === "error" && <p className="err">{job.error}</p>}
        </div>
      )}

      {done && jobId && (
        <div className="card">
          <video controls src={`/api/jobs/${jobId}/video`} />
          <a className="dl" href={`/api/jobs/${jobId}/video?download=1`}>
            Télécharger la vidéo
          </a>
        </div>
      )}
    </main>
  );
}
