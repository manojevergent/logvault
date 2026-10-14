"use client";

import {
  Bookmark,
  CalendarClock,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  Database,
  FileCode2,
  PlusCircle,
  Settings,
  ShieldCheck,
  Users,
  Vault,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
  { href: "/jobs/new", label: "New extraction", icon: PlusCircle },
  { href: "/schedules", label: "Schedules", icon: CalendarClock },
];

const manageNav: NavItem[] = [
  { href: "/credentials", label: "Credentials", icon: KeyRound },
  { href: "/indexes", label: "Indexes", icon: Database },
  { href: "/templates", label: "Saved searches", icon: Bookmark },
  { href: "/log-formats", label: "Log formats", icon: FileCode2 },
];

const adminNav: NavItem[] = [
  { href: "/admin", label: "Admin", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group flex items-center gap-3 px-3 py-2 text-sm font-medium transition-colors duration-150",
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
      {item.label}
    </Link>
  );
}

function NavSection({
  title,
  items,
  pathname,
}: {
  title: string;
  items: NavItem[];
  pathname: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
        {title}
      </p>
      {items.map((item) => (
        <NavLink
          key={item.href}
          item={item}
          active={item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)}
        />
      ))}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-5">
        <div className="icon-3d flex h-8 w-8 items-center justify-center bg-gradient-to-br from-[#4285F4] to-[#1a56db]">
          <Vault className="h-[18px] w-[18px] text-white" strokeWidth={2.4} />
        </div>
        <span className="text-[15px] font-semibold tracking-tight">LogVault</span>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <NavSection title="Extract" items={primaryNav} pathname={pathname} />
        <NavSection title="Manage" items={manageNav} pathname={pathname} />
        <NavSection title="Organization" items={adminNav} pathname={pathname} />
      </nav>

      <div className="border-t border-border px-5 py-3">
        <p className="font-mono text-[11px] text-muted-foreground">v0.1.0 · internal</p>
      </div>
    </aside>
  );
}
