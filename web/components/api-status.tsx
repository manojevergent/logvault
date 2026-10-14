"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchReady } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Small live indicator of backend reachability, shown in the topbar. */
export function ApiStatus() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["ready"],
    queryFn: ({ signal }) => fetchReady(signal),
    refetchInterval: 15000,
    retry: false,
  });

  const state = isLoading
    ? { label: "Connecting", color: "bg-muted-foreground", pulse: true }
    : isError
      ? { label: "API offline", color: "bg-danger", pulse: false }
      : data?.status === "ok"
        ? { label: "All systems go", color: "bg-success", pulse: false }
        : { label: "Degraded", color: "bg-warning", pulse: false };

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5"
      title={data ? JSON.stringify(data.checks) : undefined}
    >
      <span className="relative flex h-2 w-2">
        {state.pulse && (
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-pulse-soft rounded-full opacity-75",
              state.color
            )}
          />
        )}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", state.color)} />
      </span>
      <span className="text-xs font-medium text-muted-foreground">{state.label}</span>
    </div>
  );
}
