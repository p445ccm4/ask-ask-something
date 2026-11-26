import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string }> }
) {
  const { projectId, suiteId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(
      suiteId
    )}/runs${qs ? `?${qs}` : ""}`
  );
}
