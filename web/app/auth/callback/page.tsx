"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { setToken } from "@/lib/api";

// Landing page for the API's Google OAuth callback, which redirects here with
// the session in the URL *fragment* (#access_token=...). Fragments never reach
// any server log, and this page wipes it from the address bar as soon as the
// token is stored.
function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

export default function GoogleCallbackPage() {
  const router = useRouter();
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("access_token");
    const role = params.get("role") ?? "member";
    const next = safeNext(params.get("next"));
    if (!token) {
      setError("Google sign-in did not return a session. Try again.");
      return;
    }
    setToken(token, role);
    // Drop the fragment before landing: no token lingering in history.
    window.history.replaceState(null, "", window.location.pathname);
    router.replace(next);
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-3 text-center">
        {error ? (
          <>
            <p className="text-sm text-danger">{error}</p>
            <a href="/login" className="text-sm text-primary underline">
              Back to sign in
            </a>
          </>
        ) : (
          <>
            <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Finishing Google sign-in…</p>
          </>
        )}
      </div>
    </div>
  );
}
