import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return proxyJson("/workspaces");
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  return proxyJson("/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
