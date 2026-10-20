import { NextResponse } from "next/server";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const res = await backend(`/jobs/${encodeURIComponent(id)}`);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { detail: e instanceof Error ? e.message : "Erreur serveur" },
      { status: 500 }
    );
  }
}
