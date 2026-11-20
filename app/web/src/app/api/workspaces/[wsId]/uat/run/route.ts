import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ wsId: string }> }
) {
  const { wsId } = await context.params;
  const body = await req.text();
  return proxyJson(`/workspaces/${encodeURIComponent(wsId)}/uat/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
