import { NextRequest } from "next/server";
import { proxySse } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ convId: string }> }
) {
  const { convId } = await context.params;
  const body = await req.text();
  return proxySse(`/conversations/${encodeURIComponent(convId)}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
