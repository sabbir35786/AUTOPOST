import type { Metadata } from "next";
import { GeistMono, GeistSans } from "geist/font";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Auto Poster",
  description: "AI-assisted Facebook page posting dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
