import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AskAsk* Workbench — UAT & Antigravity Maintainer",
  description:
    "Next.js + Antigravity SDK workbench for multi-repo UAT debugging, sandboxed fixes, and DEV/UAT deployments.",
};

const THEME_INIT_SCRIPT = `
(function() {
  try {
    var stored = localStorage.getItem("ag-workbench-theme");
    var isDark = stored === "dark" || (stored !== "light" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.style.colorScheme = isDark ? "dark" : "light";
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="bg-bea-canvas text-bea-text-primary antialiased selection:bg-bea-coral/40 selection:text-bea-burgundy">
        {children}
      </body>
    </html>
  );
}
