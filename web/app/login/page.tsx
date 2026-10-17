"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { API_BASE, getAuthProviders, loginUser, setToken } from "@/lib/api";

// Error codes the API's Google callback redirects back with (?error=<code>).
const GOOGLE_ERRORS: Record<string, string> = {
  denied: "Google sign-in was cancelled. Try again or use email + password.",
  domain: "That Google account's domain is not allowed here.",
  unverified: "That Google account's email is not verified.",
  oauth_failed: "Google sign-in failed. Try again or use email + password.",
  invalid_state: "The sign-in attempt expired. Try again.",
  disabled: "Google sign-in is not enabled on this server.",
};

function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [googleEnabled, setGoogleEnabled] = React.useState(false);
  const [from, setFrom] = React.useState("/");

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setFrom(safeNext(params.get("from")));
    const googleError = params.get("error");
    if (googleError) setError(GOOGLE_ERRORS[googleError] ?? "Google sign-in failed.");
    getAuthProviders()
      .then((p) => setGoogleEnabled(p.google))
      .catch(() => {});
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result = await loginUser(email, password);
      setToken(result.access_token, result.role);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">LogVault</h1>
          <p className="text-sm text-muted-foreground">Sign in to your account</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label>Password</Label>
            <Input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            Sign in
          </Button>
        </form>
        {googleEnabled && (
          <>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              or
              <span className="h-px flex-1 bg-border" />
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => {
                window.location.href = `${API_BASE}/auth/google/login?next=${encodeURIComponent(from)}`;
              }}
            >
              Continue with Google
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
