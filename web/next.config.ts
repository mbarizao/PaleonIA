import fs from "fs";
import path from "path";
import type { NextConfig } from "next";

function apiOrigin() {
  if (process.env.PALEONIA_API_URL) return process.env.PALEONIA_API_URL.replace(/\/$/, "");
  try {
    const envFile = fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8");
    const match = envFile.match(/^PALEONIA_PORT=(.+)$/m);
    const port = (match?.[1] || "8878").trim();
    return `http://127.0.0.1:${port}`;
  } catch {
    return "http://127.0.0.1:8878";
  }
}

const api = apiOrigin();

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  experimental: {
    // A detecção de linhas pode levar minutos; o proxy do Next corta em 30s.
    proxyTimeout: 600_000,
    // O padrão de 10 MB corta o upload e a API recebe o corpo pela metade.
    middlewareClientMaxBodySize: "512mb",
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/images/:path*", destination: `${api}/images/:path*` },
      { source: "/brand/:path*", destination: `${api}/brand/:path*` },
    ];
  },
};

export default nextConfig;
