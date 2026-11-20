import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  _req: NextRequest,
  context: { params: Promise<{ convId: string }> }
) {
  const { convId } = await context.params;
  return proxyJson(`/conversations/${encodeURIComponent(convId)}/cancel`, {
    method: "POST",
  });
}
