"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Bookmark,
  CalendarClock,
  Database,
  FileText,
  Layers,
  PlusCircle,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { fieldClass } from "@/components/ui/input";
import {
  FilterTemplate,
  GroupSummary,
  IndexTarget,
  Job,
  Schedule,
  listGroups,
  listIndexes,
  listSchedules,
  listTemplates,
} from "@/lib/api";
import { useJobs } from "@/lib/use-jobs";
import { cn } from "@/lib/utils";

export const OPEN_PALETTE_EVENT = "logvault:open-palette";

type Hit = {
  key: string;
  group: string;
  label: string;
  sub: string;
  href: string;
};

const CREATE_HITS: Hit[] = [
  {
    key: "create-extraction",
    group: "Create",
    label: "New extraction",
    sub: "action",
    href: "/jobs/new",
  },
  {
    key: "create-group",
    group: "Create",
    label: "New group extraction",
    sub: "action",
    href: "/groups/new",
  },
];

const PAGE_HITS: Hit[] = [
  { key: "page-reports", group: "Go to", label: "Reports", sub: "page", href: "/reports" },
  {
    key: "page-groups",
    group: "Go to",
    label: "Group extractions",
    sub: "page",
    href: "/groups",
  },
  { key: "page-jobs", group: "Go to", label: "Jobs", sub: "page", href: "/jobs" },
  {
    key: "page-customers",
    group: "Go to",
    label: "Customers",
    sub: "page",
    href: "/customers",
  },
  {
    key: "page-schedules",
    group: "Go to",
    label: "Schedules",
    sub: "page",
    href: "/schedules",
  },
  {
    key: "page-templates",
    group: "Go to",
    label: "Saved searches",
    sub: "page",
    href: "/templates",
  },
  {
    key: "page-formats",
    group: "Go to",
    label: "Log formats",
    sub: "page",
    href: "/log-formats",
  },
  { key: "page-indexes", group: "Go to", label: "Indexes", sub: "page", href: "/indexes" },
  {
    key: "page-credentials",
    group: "Go to",
    label: "Credentials",
    sub: "page",
    href: "/credentials",
  },
  {
    key: "page-compare",
    group: "Go to",
    label: "Compare",
    sub: "page",
    href: "/compare",
  },
  {
    key: "page-newrelic",
    group: "Go to",
    label: "New Relic",
    sub: "page",
    href: "/new-relic",
  },
  {
    key: "page-s3",
    group: "Go to",
    label: "S3 destinations",
    sub: "page",
    href: "/s3-profiles",
  },
  {
    key: "page-admin",
    group: "Go to",
    label: "Admin",
    sub: "page",
    href: "/admin",
  },
  {
    key: "page-settings",
    group: "Go to",
    label: "Settings",
    sub: "page",
    href: "/settings",
  },
];

function matchWords(hay: string, q: string): boolean {
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.toLowerCase().includes(word));
}

const PER_GROUP = 8;

function Section({
  title,
  icon,
  items,
  activeKey,
  onGo,
  onHover,
}: {
  title: string;
  icon: React.ReactNode;
  items: Hit[];
  activeKey: string | null;
  onGo: (h: Hit) => void;
  onHover: (key: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
        {icon}
        {title}
      </p>
      <ul>
        {items.map((h) => (
          <li key={h.key}>
            <button
              type="button"
              id={`palette-${h.key}`}
              onClick={() => onGo(h)}
              onMouseEnter={() => onHover(h.key)}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm",
                h.key === activeKey ? "bg-muted text-foreground" : "text-muted-foreground"
              )}
            >
              <span className="min-w-0 flex-1 truncate font-medium">{h.label}</span>
              <span className="shrink-0 font-mono text-xs opacity-70">{h.sub}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Global ⌘K palette. The topbar pill used to be a dead placeholder — this is
 *  the working version: one keystroke searches jobs, saved searches, indexes
 *  and schedules from any page. Mounted once in the app shell. */
export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeKey, setActiveKey] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const { data: jobs } = useJobs();
  const { data: templates } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
    enabled: open,
  });
  const { data: indexes } = useQuery({
    queryKey: ["indexes", ""],
    queryFn: () => listIndexes(),
    enabled: open,
  });
  const { data: schedules } = useQuery({
    queryKey: ["schedules"],
    queryFn: listSchedules,
    enabled: open,
  });
  const { data: groupList } = useQuery({
    queryKey: ["groups", "palette"],
    queryFn: () => listGroups(50),
    enabled: open,
  });

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    function onOpen() {
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
    };
  }, []);

  React.useEffect(() => {
    if (open) {
      setQuery("");
      setActiveKey(null);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const groups = React.useMemo(() => {
    const q = query.trim();
    const keep = (hay: string) => !q || matchWords(hay, q);

    const createHits = CREATE_HITS.filter((hit) => keep(`${hit.label} ${hit.sub}`));
    const pageHits = PAGE_HITS.filter((hit) => keep(`${hit.label} ${hit.sub}`));

    const jobHits: Hit[] = (jobs ?? [])
      .filter((j: Job) => keep(`${j.id} ${j.filter_spec?.label ?? ""} ${j.status}`))
      .slice(0, PER_GROUP)
      .map((j) => ({
        key: `job-${j.id}`,
        group: "Jobs",
        label: j.filter_spec?.label ? `#${j.id} ${j.filter_spec.label}` : `Job #${j.id}`,
        sub: j.status,
        href: `/jobs/${j.id}`,
      }));
    const tplHits: Hit[] = (templates ?? [])
      .filter((t: FilterTemplate) => keep(`${t.name} ${t.customer ?? ""}`))
      .slice(0, PER_GROUP)
      .map((t) => ({
        key: `tpl-${t.id}`,
        group: "Saved searches",
        label: t.name,
        sub: t.customer ?? "",
        href: "/templates",
      }));
    const groupHits: Hit[] = (groupList ?? [])
      .filter((g: GroupSummary) => keep(`${g.name} ${g.status}`))
      .slice(0, PER_GROUP)
      .map((g) => ({
        key: `grp-${g.id}`,
        group: "Groups",
        label: g.name,
        sub: g.status,
        href: `/groups/${g.id}`,
      }));
    const customerHits: Hit[] = [];
    const seenCustomers = new Set<string>();
    for (const job of jobs ?? []) {
      const customer = job.filter_spec?.customer?.trim();
      if (!customer || seenCustomers.has(customer) || !keep(customer)) continue;
      seenCustomers.add(customer);
      customerHits.push({
        key: `cust-${customer}`,
        group: "Customers",
        label: customer,
        sub: "customer",
        href: `/jobs?q=${encodeURIComponent(customer)}`,
      });
      if (customerHits.length >= PER_GROUP) break;
    }
    const idxHits: Hit[] = (indexes ?? [])
      .filter((i: IndexTarget) => keep(`${i.name} ${i.region_code}`))
      .slice(0, PER_GROUP)
      .map((i) => ({
        key: `idx-${i.id}`,
        group: "Indexes",
        label: i.name,
        sub: i.region_code,
        href: "/indexes",
      }));
    const schHits: Hit[] = (schedules ?? [])
      .filter((s: Schedule) => keep(s.name))
      .slice(0, PER_GROUP)
      .map((s) => ({
        key: `sch-${s.id}`,
        group: "Schedules",
        label: s.name,
        sub: s.enabled ? "on" : "off",
        href: "/schedules",
      }));

    return [
      { title: "Create", icon: <PlusCircle className="h-3 w-3" />, hits: createHits },
      { title: "Go to", icon: <BarChart3 className="h-3 w-3" />, hits: pageHits },
      { title: "Jobs", icon: <FileText className="h-3 w-3" />, hits: jobHits },
      { title: "Saved searches", icon: <Bookmark className="h-3 w-3" />, hits: tplHits },
      { title: "Groups", icon: <Layers className="h-3 w-3" />, hits: groupHits },
      { title: "Customers", icon: <Users className="h-3 w-3" />, hits: customerHits },
      { title: "Indexes", icon: <Database className="h-3 w-3" />, hits: idxHits },
      { title: "Schedules", icon: <CalendarClock className="h-3 w-3" />, hits: schHits },
    ];
  }, [jobs, templates, indexes, schedules, groupList, query]);

  const flat = React.useMemo(() => groups.flatMap((g) => g.hits), [groups]);
  const total = flat.length;

  function go(h: Hit) {
    setOpen(false);
    router.push(h.href);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto p-4 pt-[12vh]">
      <button
        type="button"
        aria-hidden
        tabIndex={-1}
        className="fixed inset-0 cursor-default bg-background/80 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />
      <div className="relative w-full max-w-xl border border-border bg-background shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-3">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveKey(null);
            }}
            onKeyDown={(e) => {
              if (flat.length === 0) return;
              const i = flat.findIndex((h) => h.key === activeKey);
              if (e.key === "ArrowDown") {
                e.preventDefault();
                const next = flat[(i + 1) % flat.length];
                setActiveKey(next.key);
                document
                  .getElementById(`palette-${next.key}`)
                  ?.scrollIntoView({ block: "nearest" });
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                const prev = flat[(i - 1 + flat.length) % flat.length];
                setActiveKey(prev.key);
                document
                  .getElementById(`palette-${prev.key}`)
                  ?.scrollIntoView({ block: "nearest" });
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(flat[Math.max(i, 0)]);
              }
            }}
            placeholder="Search anything — jobs, groups, customers, searches…"
            aria-label="Global search"
            className={cn(fieldClass, "h-11 border-0 text-sm shadow-none focus-visible:ring-0")}
          />
          <kbd className="shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            esc
          </kbd>
        </div>
        <div className="max-h-[50vh] overflow-auto py-1">
          {total === 0 && (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              {query.trim() ? `No matches for “${query.trim()}”.` : "Loading…"}
            </p>
          )}
          {groups.map((g) => (
            <Section
              key={g.title}
              title={`${g.title} · ${g.hits.length}`}
              icon={g.icon}
              items={g.hits}
              activeKey={activeKey}
              onGo={go}
              onHover={setActiveKey}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
