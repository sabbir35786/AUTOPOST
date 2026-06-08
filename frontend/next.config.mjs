/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Skip rewrites when running locally with a local backend
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "";
    if (backendUrl.startsWith("http://localhost")) {
      return [];
    }
    return [
      {
        source: "/backend/:path*",
        destination: "https://auto-poster-backend.onrender.com/:path*",
      },
    ];
  },
};

export default nextConfig;
