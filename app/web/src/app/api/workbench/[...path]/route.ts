import { createWorkbenchCatchAllHandlers } from "@ag-workbench/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const { GET, POST, PATCH, DELETE } = createWorkbenchCatchAllHandlers();
