import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DeepTune RL — Rollouts",
  description: "Job submission + transcript review for the Metabase RL environment",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
        <header className="border-b border-neutral-200 dark:border-neutral-800 px-6 py-3 flex items-center justify-between bg-white dark:bg-neutral-900">
          <a href="/" className="font-semibold tracking-tight">
            DeepTune RL{" "}
            <span className="text-neutral-400 font-normal">/ Rollouts</span>
          </a>
          <a
            href="/jobs/new"
            className="text-sm px-3 py-1.5 rounded-md bg-neutral-900 text-white dark:bg-white dark:text-neutral-900 hover:opacity-90"
          >
            New job
          </a>
        </header>
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
