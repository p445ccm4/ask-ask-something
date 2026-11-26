import { NextRequest } from "next/server";
import { AGENT_SERVICE_URL } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ wsId: string }> }
) {
  const { wsId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  const upstream = await fetch(
    `${AGENT_SERVICE_URL}/workspaces/${encodeURIComponent(wsId)}/uat/export-csv${qs ? `?${qs}` : ""}`,
    { cache: "no-store" }
  );
  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, { status: upstream.status });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${wsId}_uat_results.csv"`,
    },
  });
}
