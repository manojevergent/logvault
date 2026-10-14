"use client";

import { useQuery } from "@tanstack/react-query";
import { Job, listJobs } from "@/lib/api";

const ACTIVE_STATUSES = ["queued", "running", "paused"];

export function isActive(job: Job): boolean {
  return ACTIVE_STATUSES.includes(job.status);
}

/**
 * The one `["jobs"]` query. The dashboard, jobs list and customers page all
 * read it; when they each declared their own options, React Query merged the
 * observers onto the same key and whichever page mounted last decided the poll
 * interval for every other one.
 *
 * Polls every 5s only while something is actually running, 60s otherwise, and
 * not at all while the tab is in the background.
 */
export function useJobs(limit = 200) {
  return useQuery({
    queryKey: ["jobs", limit],
    queryFn: () => listJobs(limit),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 5_000;
      return data.some(isActive) ? 5_000 : 60_000;
    },
    refetchIntervalInBackground: false,
  });
}
