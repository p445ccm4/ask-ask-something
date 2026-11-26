import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string }> }
) {
  const { projectId, suiteId } = await context.params;
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(suiteId)}`
  );
}

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string }> }
) {
  const { projectId, suiteId } = await context.params;
  const body = await req.text();
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(suiteId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body,
    }
  );
}

export async function DELETE(
  _req: NextRequest,
  context: { params: Promise<{ projectId: string; suiteId: string }> }
) {
  const { projectId, suiteId } = await context.params;
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(suiteId)}`,
    { method: "DELETE" }
  );
}
