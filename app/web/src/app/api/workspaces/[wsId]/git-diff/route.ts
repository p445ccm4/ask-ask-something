import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ wsId: string }> }
) {
  const { wsId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(`/workspaces/${encodeURIComponent(wsId)}/git-diff${qs ? `?${qs}` : ""}`);
}
