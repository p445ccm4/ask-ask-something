import { NextRequest } from "next/server";
import { proxySse } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await context.params;
  return proxySse(`/uat/jobs/${encodeURIComponent(jobId)}/stream`);
}
