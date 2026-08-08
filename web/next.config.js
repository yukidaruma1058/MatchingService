const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker 本番イメージ用。next build 時は常に standalone
  output: "standalone",
  webpack: (config) => {
    // tsconfig paths に依存せず @ を解決（Alpine ビルドでの Module not found 対策）
    config.resolve.alias = {
      ...(config.resolve.alias || {}),
      "@": path.resolve(__dirname),
    };
    return config;
  },
};

module.exports = nextConfig;
