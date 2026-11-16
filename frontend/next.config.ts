import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  // Mirror search API (shape_search/api.py) during development
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.SEARCH_API ?? "http://127.0.0.1:8787"}/:path*` }];
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
