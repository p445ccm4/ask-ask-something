import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AskAsk* Workbench — UAT & Antigravity Maintainer",
  description:
    "Next.js + Antigravity SDK workbench for multi-repo UAT debugging, sandboxed fixes, and DEV/UAT deployments.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-bea-canvas text-bea-text-primary antialiased selection:bg-bea-coral/40 selection:text-bea-burgundy">
        {children}
      </body>
    </html>
  );
}
