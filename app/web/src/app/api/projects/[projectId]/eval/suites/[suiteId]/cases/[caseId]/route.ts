import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string; caseId: string }> }
) {
  const { projectId, suiteId, caseId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(
      suiteId
    )}/cases/${encodeURIComponent(caseId)}${qs ? `?${qs}` : ""}`
  );
}

export async function DELETE(
  _req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string; caseId: string }> }
) {
  const { projectId, suiteId, caseId } = await context.params;
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(
      suiteId
    )}/cases/${encodeURIComponent(caseId)}`,
    { method: "DELETE" }
  );
}
