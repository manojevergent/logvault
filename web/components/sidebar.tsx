"use client";

import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  Bookmark,
  CalendarClock,
  CloudUpload,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  Database,
  FileCode2,
  PanelLeftClose,
  PanelLeftOpen,
  PlusCircle,
  Settings,
  ShieldCheck,
  Users,
  Vault,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const primaryNav: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/reports", label: "Reports", icon: BarChart3 },
  { href: "/jobs/new", label: "New extraction", icon: PlusCircle },
  { href: "/schedules", label: "Schedules", icon: CalendarClock },
  { href: "/compare", label: "Compare", icon: ArrowLeftRight },
];

const manageNav: NavItem[] = [
  { href: "/credentials", label: "Credentials", icon: KeyRound },
  { href: "/new-relic", label: "New Relic", icon: Activity },
  { href: "/s3-profiles", label: "S3 destinations", icon: CloudUpload },
  { href: "/indexes", label: "Indexes", icon: Database },
  { href: "/templates", label: "Saved searches", icon: Bookmark },
  { href: "/log-formats", label: "Log formats", icon: FileCode2 },
];

const adminNav: NavItem[] = [
  { href: "/admin", label: "Admin", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

const ALL_NAV = [...primaryNav, ...manageNav, ...adminNav];

/**
 * The single item that owns the current path — longest match wins.
 *
 * A plain startsWith() highlighted BOTH "Jobs" (/jobs) and "New extraction"
 * (/jobs/new) on the wizard, and would likewise have lit "Jobs" while viewing
 * /jobs/123. Segment-aware prefixes plus longest-match fixes both.
 */
export function activeHref(pathname: string): string | null {
  const matches = ALL_NAV.map((n) => n.href).filter((href) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  });
  if (matches.length === 0) return null;
  return matches.sort((a, b) => b.length - a.length)[0];
}

function NavLink({
  item,
  active,
  onNavigate,
  collapsed = false,
}: {
  item: NavItem;
  active: boolean;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "group flex items-center gap-2.5 py-1.5 text-[13px] font-medium transition-colors duration-150",
        collapsed ? "justify-center px-0" : "px-2.5",
        active
          ? "bg-primary/10 font-semibold text-primary"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
      )}
    >
      <Icon
        className={cn(
          "h-4 w-4 shrink-0 transition-colors",
          active ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
        )}
      />
      {!collapsed && item.label}
    </Link>
  );
}

function NavSection({
  title,
  items,
  current,
  onNavigate,
  collapsed = false,
}: {
  title: string;
  items: NavItem[];
  current: string | null;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {collapsed ? (
        <div className="mx-2 my-1 border-t border-border" aria-hidden />
      ) : (
        <p className="px-2.5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
          {title}
        </p>
      )}
      {items.map((item) => (
        <NavLink
          key={item.href}
          item={item}
          active={current === item.href}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
      ))}
    </div>
  );
}

function SidebarBody({
  current,
  onNavigate,
  onClose,
  collapsed = false,
  onToggle,
}: {
  current: string | null;
  onNavigate?: () => void;
  onClose?: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  return (
    <>
      <div
        className={cn(
          "flex h-[52px] items-center gap-2.5 border-b border-border",
          collapsed ? "justify-center px-2" : "justify-between px-3.5"
        )}
      >
        <div className="flex items-center gap-2.5">
          <div className="icon-3d flex h-8 w-8 items-center justify-center bg-gradient-to-br from-[#4285F4] to-[#1a56db]">
            <Vault className="h-[18px] w-[18px] text-white" strokeWidth={2.4} />
          </div>
          {!collapsed && <span className="text-[15px] font-semibold tracking-tight">LogVault</span>}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="flex h-8 w-8 items-center justify-center text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav
        className={cn("flex-1 overflow-y-auto pb-3 scrollbar-thin", collapsed ? "px-1.5" : "px-2")}
      >
        <NavSection
          title="Extract"
          items={primaryNav}
          current={current}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
        <NavSection
          title="Manage"
          items={manageNav}
          current={current}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
        <NavSection
          title="Organization"
          items={adminNav}
          current={current}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
      </nav>

      <div
        className={cn(
          "border-t border-border",
          collapsed ? "flex justify-center px-2 py-2" : "px-3.5 py-2.5"
        )}
      >
        {collapsed ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label="Expand sidebar"
            aria-expanded={false}
            title="Expand sidebar"
            className="flex h-7 w-7 items-center justify-center text-muted-foreground hover:text-foreground"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[11px] text-muted-foreground">v0.1.0 · internal</p>
            <button
              type="button"
              onClick={onToggle}
              aria-label="Collapse sidebar"
              aria-expanded
              title="Collapse sidebar"
              className="flex h-7 w-7 items-center justify-center text-muted-foreground hover:text-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </>
  );
}

/** Desktop rail. Hidden below md — see MobileSidebar for the small-screen path.
 *  Collapses to an icon rail (64px) and remembers the choice. */
export function Sidebar({
  collapsed = false,
  onToggle,
}: {
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  const pathname = usePathname();
  const current = activeHref(pathname);
  return (
    <aside
      className={cn(
        // 15% tighter than the original 240px, with the internal rhythm
        // (gaps, padding) scaled to match so it reads denser, not cramped.
        "hidden shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-150 md:flex",
        collapsed ? "w-16" : "w-[204px]"
      )}
    >
      <SidebarBody current={current} collapsed={collapsed} onToggle={onToggle} />
    </aside>
  );
}

/**
 * Slide-over navigation for < md, where the rail is hidden and there was
 * previously no way to move between pages at all.
 */
export function MobileSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const current = activeHref(pathname);

  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    // Freeze the page behind the drawer.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 md:hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Navigation"
    >
      <button
        type="button"
        aria-hidden
        tabIndex={-1}
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-xl animate-fade-in">
        <SidebarBody current={current} onNavigate={onClose} onClose={onClose} collapsed={false} />
      </aside>
    </div>
  );
}
