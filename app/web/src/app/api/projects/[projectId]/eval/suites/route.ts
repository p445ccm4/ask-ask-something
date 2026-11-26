import { NextRequest } from "next/server";
import { proxyJson } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ projectId: string }> }
) {
  const { projectId } = await context.params;
  const qs = req.nextUrl.searchParams.toString();
  return proxyJson(
    `/projects/${encodeURIComponent(projectId)}/eval/suites${qs ? `?${qs}` : ""}`
  );
}

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ projectId: string }> }
) {
  const { projectId } = await context.params;
  const body = await req.text();
  return proxyJson(`/projects/${encodeURIComponent(projectId)}/eval/suites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
