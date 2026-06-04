/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: "https://autopost-1-ax2p.onrender.com/:path*",
      },
    ];
  },
};

export default nextConfig;
