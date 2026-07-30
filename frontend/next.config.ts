import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output: the Docker runner stage ships only server.js + the
  // pruned node_modules subset, not the full build toolchain.
  output: "standalone",
  // All backend traffic goes through the auth-injecting Route Handler at
  // /api/backend/[...path] (same-origin => no CORS, and the X-API-Key never
  // reaches the browser). Plain `rewrites` cannot inject request headers,
  // which is why a Route Handler proxy is used instead.
};

export default nextConfig;
