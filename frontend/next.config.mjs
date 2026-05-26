/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: "https://autopost-qwgw.onrender.com/:path*",
      },
    ];
  },
};

export default nextConfig;
