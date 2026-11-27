import { createScopedProxyHandlers } from "@/server/backendClient";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const { GET, POST, PATCH, DELETE } = createScopedProxyHandlers([
  "health",
  "projects",
  "eval",
  "workspaces",
]);
