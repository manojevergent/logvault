"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { FieldGroup, Input, Label } from "@/components/ui/input";
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

// The login page is the vault door: a flat navy plate with an engineered
// hairline grid, one chamfered "aperture" plate, and a paper access card.
// Geometry stays sharp everywhere — no radii, no gradients, no soft shadows.
const CHAMFER =
  "polygon(0 22px, 22px 0, calc(100% - 22px) 0, 100% 22px, 100% calc(100% - 22px), calc(100% - 22px) 100%, 22px 100%, 0 calc(100% - 22px))";
const CHAMFER_INNER =
  "polygon(0 21px, 21px 0, calc(100% - 21px) 0, 100% 21px, 100% calc(100% - 21px), calc(100% - 21px) 100%, 21px 100%, 0 calc(100% - 21px))";

const GRID: React.CSSProperties = {
  backgroundImage:
    "linear-gradient(to right, rgba(242,239,232,0.055) 1px, transparent 1px), " +
    "linear-gradient(to bottom, rgba(242,239,232,0.055) 1px, transparent 1px)",
  backgroundSize: "72px 72px",
};

/** Viewfinder brackets around three log lines: the extraction frame. */
function VaultMark() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M4 9V4h5M21 4h5v5M26 21v5h-5M9 26H4v-5" stroke="#F2EFE8" strokeWidth="1.5" />
      <path d="M10 11h10M10 15h10M10 19h6" stroke="#C8A96A" strokeWidth="1.5" />
    </svg>
  );
}

/** The official four-colour Google G, for the OAuth button. */
function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true" className="shrink-0">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [formError, setFormError] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [googleEnabled, setGoogleEnabled] = React.useState(false);
  const [from, setFrom] = React.useState("/");

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setFrom(safeNext(params.get("from")));
    const googleError = params.get("error");
    if (googleError) {
      setError(GOOGLE_ERRORS[googleError] ?? "Google sign-in failed.");
      setFormError(false);
    }
    getAuthProviders()
      .then((p) => setGoogleEnabled(p.google))
      .catch(() => {});
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setFormError(false);
    setLoading(true);
    try {
      const result = await loginUser(email, password);
      setToken(result.access_token, result.role);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
      setFormError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#0A1F44] text-[#F2EFE8]">
      {/* Engineering-drawing grid: 1px lines at low opacity, behind everything. */}
      <div aria-hidden className="pointer-events-none absolute inset-0" style={GRID} />

      <div className="relative mx-auto flex min-h-screen w-full max-w-[1240px] flex-col px-6 py-8 sm:px-10 lg:grid lg:grid-cols-[1.02fr_0.98fr] lg:items-stretch lg:gap-20 lg:px-14 lg:py-14">
        {/* ---- Brand plate: the thesis, the subject's own ledger ---- */}
        <section className="relative flex flex-col lg:h-full lg:justify-between lg:py-2">
          <div className="flex items-center gap-3">
            <VaultMark />
            <div>
              <div className="text-[15px] font-semibold tracking-[-0.01em] text-[#F2EFE8]">LogVault</div>
              <div className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.22em] text-[#C8A96A]/80">
                Evergent · Internal
              </div>
            </div>
          </div>

          <div className="mt-10 lg:mt-0">
            <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-[#C8A96A]">
              Log extraction platform
            </p>
            <h1 className="mt-5 max-w-[15ch] text-[clamp(2rem,5vw,3.5rem)] font-semibold leading-[1.02] tracking-[-0.035em] text-[#F2EFE8]">
              Every extracted line, accounted for<span className="text-[#C8A96A]">.</span>
            </h1>
            <p className="mt-5 max-w-[40ch] text-[14.5px] leading-relaxed text-[#F2EFE8]/60">
              Hours-long extractions stream to CSV — checkpointed, resumable, and audited end to end.
            </p>
          </div>

          {/* Illustrative ledger, not real job data. Decorative only. */}
          <div className="mt-12 hidden lg:mt-0 lg:block" aria-hidden="true">
            <div className="h-px w-full bg-[#F2EFE8]/10" />
            <div className="mt-4 space-y-1.5 overflow-hidden font-mono text-[10px] leading-relaxed text-[#F2EFE8]/40">
              <div className="whitespace-pre">
                <span className="text-[#C8A96A]/70">04:00:00Z</span>  stream open   ap-south-1  index=prod-logs
              </div>
              <div className="whitespace-pre">
                <span className="text-[#C8A96A]/70">04:12:40Z</span>  chunk 07/24   rows 1,284,006  checkpoint ok
              </div>
              <div className="whitespace-pre">
                <span className="text-[#C8A96A]/70">04:31:08Z</span>  retry 03/10   upstream 503   backoff 40s
              </div>
              <div className="whitespace-pre">
                <span className="text-[#C8A96A]/70">04:58:22Z</span>  csv final     signed url issued
              </div>
            </div>
            <div className="mt-5 flex items-center justify-between gap-6 font-mono text-[9px] uppercase tracking-[0.18em] text-[#F2EFE8]/30">
              <span>Internal use only</span>
              <span>ap-south-1 · us-east-1 · ap-southeast-1 · eu-central-1</span>
            </div>
          </div>
        </section>

        {/* ---- Aperture plate + paper access card ---- */}
        <section className="relative mt-10 flex items-center lg:mt-0">
          <div className="relative mx-auto w-full max-w-[430px]">
            {/* Chamfered mounting plate: 1px hairline frame, brass rivets. */}
            <div aria-hidden className="pointer-events-none absolute -inset-4 sm:-inset-6 lg:-inset-7">
              <div
                className="absolute inset-0"
                style={{ clipPath: CHAMFER, background: "rgba(242,239,232,0.22)" }}
              >
                <div
                  className="absolute inset-px"
                  style={{ clipPath: CHAMFER_INNER, background: "#0A1F44" }}
                />
              </div>
              <span className="absolute left-[11px] top-[11px] h-1 w-1 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-[#C8A96A]" />
              <span className="absolute right-[11px] top-[11px] h-1 w-1 translate-x-1/2 -translate-y-1/2 rotate-45 bg-[#C8A96A]" />
              <span className="absolute bottom-[11px] right-[11px] h-1 w-1 translate-x-1/2 translate-y-1/2 rotate-45 bg-[#C8A96A]" />
              <span className="absolute bottom-[11px] left-[11px] h-1 w-1 -translate-x-1/2 translate-y-1/2 rotate-45 bg-[#C8A96A]" />
            </div>

            <div className="relative bg-[#F2EFE8] text-[#0A1F44]">
              {/* Inset document hairline, 10px inside the paper edge. */}
              <div
                aria-hidden
                className="pointer-events-none absolute inset-[10px] border border-[#0A1F44]/20"
              />

              <div className="relative px-6 py-8 sm:px-9 sm:py-10">
                <div className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-[#0A1F44]/70">
                  <span aria-hidden className="h-[5px] w-[5px] bg-[#C8A96A]" />
                  Access
                </div>

                <h2 className="mt-4 text-[26px] font-semibold leading-none tracking-[-0.03em] text-[#0A1F44]">
                  Sign in
                </h2>
                <p className="mt-2.5 text-[13px] leading-relaxed text-[#0A1F44]/65">
                  Use your work account to continue.
                </p>

                <form onSubmit={onSubmit} className="mt-7 space-y-4" aria-busy={loading || undefined}>
                  <FieldGroup>
                    <div className="space-y-2">
                      <Label className="block font-mono text-[9.5px] uppercase tracking-[0.2em] text-[#0A1F44]/70">
                        Email
                      </Label>
                      <Input
                        type="email"
                        autoComplete="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        aria-invalid={formError || undefined}
                        aria-describedby={formError ? "login-error" : undefined}
                        className="h-11 border-[#0A1F44]/50 bg-[#FBFAF6] px-3.5 text-[15px] text-[#0A1F44] focus-visible:border-[#0A1F44] focus-visible:ring-2 focus-visible:ring-[#0A1F44] focus-visible:ring-offset-2 focus-visible:ring-offset-[#F2EFE8]"
                      />
                    </div>
                  </FieldGroup>

                  <FieldGroup>
                    <div className="space-y-2">
                      <Label className="block font-mono text-[9.5px] uppercase tracking-[0.2em] text-[#0A1F44]/70">
                        Password
                      </Label>
                      <Input
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        aria-invalid={formError || undefined}
                        aria-describedby={formError ? "login-error" : undefined}
                        className="h-11 border-[#0A1F44]/50 bg-[#FBFAF6] px-3.5 text-[15px] text-[#0A1F44] focus-visible:border-[#0A1F44] focus-visible:ring-2 focus-visible:ring-[#0A1F44] focus-visible:ring-offset-2 focus-visible:ring-offset-[#F2EFE8]"
                      />
                    </div>
                  </FieldGroup>

                  {error && (
                    <div
                      id="login-error"
                      role="alert"
                      className="border-l-2 border-[#A8231B] bg-[#A8231B]/5 px-3 py-2"
                    >
                      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-[#A8231B]">
                        Error
                      </p>
                      <p className="mt-1 text-[12.5px] leading-snug text-[#A8231B]">{error}</p>
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={loading}
                    aria-busy={loading || undefined}
                    className="group flex h-12 w-full items-center justify-between bg-[#0A1F44] px-5 text-[15px] font-medium text-[#F2EFE8] transition-colors duration-150 hover:bg-[#122B57] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0A1F44] focus-visible:ring-offset-2 focus-visible:ring-offset-[#F2EFE8] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span className="flex items-center gap-2">
                      {loading && <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />}
                      {loading ? "Signing in…" : "Sign in"}
                    </span>
                    <ArrowRight
                      aria-hidden
                      className="h-4 w-4 transition-transform duration-150 motion-safe:group-hover:translate-x-0.5"
                    />
                  </button>
                </form>

                {googleEnabled && (
                  <>
                    <div className="my-6 flex items-center gap-3">
                      <span aria-hidden className="h-px flex-1 bg-[#0A1F44]/10" />
                      <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-[#0A1F44]/65">
                        or
                      </span>
                      <span aria-hidden className="h-px flex-1 bg-[#0A1F44]/10" />
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        window.location.href = `${API_BASE}/auth/google/login?next=${encodeURIComponent(from)}`;
                      }}
                      className="flex h-11 w-full items-center justify-center gap-2.5 border border-[#0A1F44]/50 bg-transparent text-[14px] font-medium text-[#0A1F44] transition-colors duration-150 hover:bg-[#0A1F44]/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0A1F44] focus-visible:ring-offset-2 focus-visible:ring-offset-[#F2EFE8]"
                    >
                      <GoogleMark />
                      Continue with Google
                    </button>
                  </>
                )}

                <div className="mt-7 border-t border-[#0A1F44]/10 pt-4 font-mono text-[9px] uppercase tracking-[0.2em] text-[#0A1F44]/65">
                  Internal use only
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
