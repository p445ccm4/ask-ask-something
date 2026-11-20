import { NextResponse } from "next/server";

export const AGENT_SERVICE_URL =
  process.env.AGENT_SERVICE_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

export async function proxyJson(
  path: string,
  init?: RequestInit
): Promise<NextResponse> {
  const url = `${AGENT_SERVICE_URL}${path}`;
  try {
    const res = await fetch(url, {
      ...init,
      cache: "no-store",
      headers: {
        ...(init?.headers ?? {}),
      },
    });
    const text = await res.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { detail: text };
    }
    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      {
        detail: `Failed to reach agent-service at ${AGENT_SERVICE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      },
      { status: 502 }
    );
  }
}

export async function proxySse(
  path: string,
  init?: RequestInit
): Promise<Response> {
  const url = `${AGENT_SERVICE_URL}${path}`;
  try {
    const upstream = await fetch(url, {
      ...init,
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text();
      return new Response(text || "Upstream stream error", {
        status: upstream.status || 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    return NextResponse.json(
      {
        detail: `SSE proxy failed for ${AGENT_SERVICE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      },
      { status: 502 }
    );
  }
}
