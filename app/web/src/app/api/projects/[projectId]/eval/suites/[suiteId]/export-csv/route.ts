import { NextRequest } from "next/server";
import { AGENT_SERVICE_URL } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string }> }
) {
  const { projectId, suiteId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  const upstream = await fetch(
    `${AGENT_SERVICE_URL}/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(
      suiteId
    )}/export-csv${qs ? `?${qs}` : ""}`,
    { cache: "no-store" }
  );
  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" },
    });
  }
  const cd =
    upstream.headers.get("content-disposition") ||
    `attachment; filename="${suiteId}_eval_results.csv"`;
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": cd,
    },
  });
}
