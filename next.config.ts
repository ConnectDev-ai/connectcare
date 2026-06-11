import type { NextConfig } from "next";

// Base URL of the existing Flask API (Scripts/web_app.py).
// In dev the Flask API runs on :5000; override with FLASK_API_URL in prod/Vercel.
const FLASK = process.env.FLASK_API_URL ?? "http://localhost:5000";

const nextConfig: NextConfig = {
  // Proxy /backend/* -> Flask /api/* so the browser hits a same-origin path
  // (no CORS) and the backend URL stays configurable per environment.
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${FLASK}/api/:path*` }];
  },
};

export default nextConfig;
