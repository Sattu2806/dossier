import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle with only the dependencies actually
  // imported, so the runtime image ships without node_modules.
  output: "standalone",
};

export default nextConfig;
