"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { ApiStatus } from "@/components/api-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { clearToken } from "@/lib/api";

export function Topbar() {
  const router = useRouter();
  const qc = useQueryClient();

  function logout() {
    clearToken();
    // Signing out is a client-side navigation, so the cache would otherwise
    // outlive the session — the next person to sign in on this browser would
    // see the previous user's jobs and credentials until each query refetched.
    qc.clear();
    router.replace("/login");
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface/80 px-6 backdrop-blur">
      <div className="flex items-center gap-3 text-sm">
        <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-muted-foreground">
          <Search className="h-3.5 w-3.5" />
          <span className="text-xs">Search jobs, indexes…</span>
          <kbd className="ml-2 hidden rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] sm:inline">
            ⌘K
          </kbd>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <ApiStatus />
        <ThemeToggle />
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
          NE
        </div>
        <button
          onClick={logout}
          aria-label="Sign out"
          className="flex h-8 w-8 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
