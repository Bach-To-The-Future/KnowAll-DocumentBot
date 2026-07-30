import type { Metadata } from "next";
import type { ReactNode } from "react";

import { LoginScreen } from "@/components/LoginScreen";
import { Nav } from "@/components/nav";
import { Providers } from "@/components/providers";
import { verifySession } from "@/lib/auth";

import "./globals.css";

export const metadata: Metadata = {
  title: "KnowAll DocumentBot",
  description: "Local-first RAG over your documents",
};

// Session state is per-request; never statically rendered or cached.
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Gate on the server so unauthenticated users never receive app markup
  // (no flash of protected content, no client-side bypass).
  const { ok } = await verifySession();

  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Providers>
          {ok ? (
            <>
              <Nav />
              <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
            </>
          ) : (
            <LoginScreen />
          )}
        </Providers>
      </body>
    </html>
  );
}
