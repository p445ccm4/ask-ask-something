import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(qs ? `/conversations?${qs}` : "/conversations");
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  return proxyJson("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
