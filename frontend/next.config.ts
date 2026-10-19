import type { NextConfig } from "next";

const apiOrigin = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' https://apis.google.com https://www.gstatic.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https://i.ytimg.com https://*.googleusercontent.com",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin} https://*.googleapis.com https://securetoken.googleapis.com https://identitytoolkit.googleapis.com`,
  "frame-src https://www.youtube-nocookie.com https://*.firebaseapp.com https://accounts.google.com",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  images: { remotePatterns: [{ protocol: "https", hostname: "i.ytimg.com" }] },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
