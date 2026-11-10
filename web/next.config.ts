import type { NextConfig } from "next";

// API port is configurable because some machines already use 8000 (docs default: 8000).
const API = `http://127.0.0.1:${process.env.API_PORT ?? "8000"}`;

const config: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] }];
  },
  allowedDevOrigins: ["*.trycloudflare.com"],
};
export default config;
