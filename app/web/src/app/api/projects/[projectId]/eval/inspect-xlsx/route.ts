import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ projectId: string }> }
) {
  const { projectId } = await context.params;
  const contentType = req.headers.get("content-type") || "";
  const body = await req.arrayBuffer();
  return proxyJson(`/projects/${encodeURIComponent(projectId)}/eval/inspect-xlsx`, {
    method: "POST",
    headers: contentType ? { "Content-Type": contentType } : undefined,
    body,
  });
}
