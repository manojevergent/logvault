"use client";

import { usePathname } from "next/navigation";
import * as React from "react";
import { CommandPalette } from "@/components/command-palette";
import { MobileSidebar, Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";

const AUTH_ROUTES = new Set(["/login"]);

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [navOpen, setNavOpen] = React.useState(false);

  // Any navigation closes the drawer, including a link tapped inside it.
  React.useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  if (AUTH_ROUTES.has(pathname)) return <>{children}</>;
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <MobileSidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setNavOpen(true)} />
        <main className="flex-1 overflow-y-auto scrollbar-thin">{children}</main>
        <CommandPalette />
      </div>
    </div>
  );
}
