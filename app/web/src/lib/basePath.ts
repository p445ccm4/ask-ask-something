const rawBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || "")
  .trim()
  .replace(/\/+$/, "");

export const BASE_PATH =
  rawBasePath && !rawBasePath.startsWith("/") ? `/${rawBasePath}` : rawBasePath;

export function apiUrl(path: string): string {
  const norm = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_PATH}${norm}`;
}
