"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { ApiStatus } from "@/components/api-status";
import { OPEN_PALETTE_EVENT } from "@/components/command-palette";
import { ThemeToggle } from "@/components/theme-toggle";
import { clearToken } from "@/lib/api";

export function Topbar({ onMenu }: { onMenu?: () => void }) {
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
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface/80 px-3 backdrop-blur sm:px-6">
      <div className="flex min-w-0 items-center gap-2 text-sm">
        {/* The rail is hidden below md; without this there is no navigation. */}
        {onMenu && (
          <button
            type="button"
            onClick={onMenu}
            aria-label="Open navigation"
            className="flex h-9 w-9 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:text-foreground md:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
        )}
        <button
          type="button"
          onClick={() => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT))}
          className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-muted-foreground transition-colors hover:text-foreground"
        >
          <Search className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate text-xs">
            <span className="hidden sm:inline">Search anything…</span>
            <span className="sm:hidden">Search…</span>
          </span>
          <kbd className="ml-2 hidden rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] sm:inline">
            ⌘K
          </kbd>
        </button>
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
