import path from "node:path";
import type { NextConfig } from "next";

const rawBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || "")
  .trim()
  .replace(/\/+$/, "");
const basePath =
  rawBasePath && !rawBasePath.startsWith("/") ? `/${rawBasePath}` : rawBasePath;

const nextConfig: NextConfig = {
  basePath: basePath || undefined,
  reactStrictMode: true,
  experimental: {
    externalDir: true,
  },
  webpack: (config) => {
    config.resolve.modules = [
      ...(config.resolve.modules ?? ["node_modules"]),
      path.resolve(__dirname, "node_modules"),
    ];
    return config;
  },
};

export default nextConfig;
