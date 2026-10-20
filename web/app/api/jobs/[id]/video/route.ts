import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

// Relaie la vidéo en streaming (la clé API reste côté serveur).
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const download = new URL(req.url).searchParams.get("download") === "1";
  const range = req.headers.get("range");
  const res = await backend(`/jobs/${encodeURIComponent(id)}/video`, {
    headers: range ? { range } : {},
  });
  if (!res.ok || !res.body) {
    return new Response("Vidéo non disponible", { status: res.status || 404 });
  }
  const headers = new Headers();
  headers.set("content-type", "video/mp4");
  const len = res.headers.get("content-length");
  if (len) headers.set("content-length", len);
  if (download) {
    headers.set("content-disposition", 'attachment; filename="video_fr.mp4"');
  }
  return new Response(res.body, { status: 200, headers });
}
