import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ wsId: string }> }
) {
  const { wsId } = await context.params;
  return proxyJson(`/workspaces/${encodeURIComponent(wsId)}/uat/overview`);
}
