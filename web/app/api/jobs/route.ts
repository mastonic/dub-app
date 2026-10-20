import { NextResponse } from "next/server";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const res = await backend("/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        url: body.url,
        voice: body.voice,
        keep_original: body.keep_original,
      }),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { detail: e instanceof Error ? e.message : "Erreur serveur" },
      { status: 500 }
    );
  }
}
