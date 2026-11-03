import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Sora } from "next/font/google";
import { AppShell } from "../components/AppShell";
import "./globals.css";

// next/font downloads these at build time and serves them from
// /_next/static/media, so the built site makes no requests to Google and the
// CSP's font-src 'self' covers them.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

// Wordmark and headings.
const sora = Sora({
  subsets: ["latin"],
  weight: ["600", "700"],
  variable: "--font-sora",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ConsultRAG",
  description: "Evidence-cited answers from your engagement documents",
  icons: { icon: [{ url: "/favicon.svg", type: "image/svg+xml" }] },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: public/theme-init.js may set data-theme on
    // <html> before React hydrates.
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${sora.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Runs before first paint so a saved theme doesn't flash. A
            same-origin file (script-src 'self'), not an inline script. */}
        <script src="/theme-init.js" />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
