import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AskAsk* Workbench — Multi-Env Eval & Maintainer",
  description:
    "Multi-environment AI Eval workbench and Antigravity SDK maintainer across SBX, DEV, UAT, and PROD repositories.",
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
