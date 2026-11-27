import { NextRequest, NextResponse } from "next/server";
import { createWorkbenchCatchAllHandlers } from "@ag-workbench/server/backendClient";

export {
  AGENT_SERVICE_URL,
  createWorkbenchCatchAllHandlers,
  proxyJson,
  proxySse,
} from "@ag-workbench/server/backendClient";

type OptionalCatchAllContext = {
  params: Promise<{ path?: string[] }>;
};

export function createScopedProxyHandlers(allowedRoots: readonly string[]) {
  const allowed = new Set(allowedRoots);
  const base = createWorkbenchCatchAllHandlers();

  const wrap =
    (
      handler: (
        req: NextRequest,
        context: { params: Promise<{ path: string[] }> }
      ) => Promise<Response>
    ) =>
    async (req: NextRequest, context: OptionalCatchAllContext) => {
      const { path } = await context.params;
      if (!path || path.length === 0 || !allowed.has(path[0])) {
        return NextResponse.json({ detail: "Not found" }, { status: 404 });
      }
      return handler(req, { params: Promise.resolve({ path }) });
    };

  return {
    GET: wrap(base.GET),
    POST: wrap(base.POST),
    PATCH: wrap(base.PATCH),
    DELETE: wrap(base.DELETE),
  };
}
