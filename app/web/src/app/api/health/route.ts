import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(qs ? `/health?${qs}` : "/health");
}
