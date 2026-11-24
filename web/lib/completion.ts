// Partial-completion presentation.
//
// The Release 1 API adds completion_state / gap_count / gap_reason to job
// responses. Older API versions omit them entirely, so every helper here treats
// a missing field as "unknown" and renders exactly as it did before.

export type CompletionState = "unknown" | "complete" | "partial";

export type CompletionInfo = {
  state: CompletionState;
  isPartial: boolean;
  isComplete: boolean;
  gapCount: number;
  gapReason: string | null;
  /** Short badge text, or null when no badge should be shown for this state. */
  label: string | null;
  /** Tooltip / inline detail, or null when there is nothing to add. */
  detail: string | null;
};

type JobLike = {
  completion_state?: string | null;
  gap_count?: number | null;
  gap_reason?: string | null;
};

const STATES: readonly CompletionState[] = ["unknown", "complete", "partial"];

function normalizeState(value: string | null | undefined): CompletionState {
  return STATES.includes(value as CompletionState) ? (value as CompletionState) : "unknown";
}

function normalizeCount(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return 0;
  return Math.trunc(value);
}

export function completionOf(job: JobLike | null | undefined): CompletionInfo {
  const state = normalizeState(job?.completion_state);
  const gapCount = normalizeCount(job?.gap_count);
  const gapReason = job?.gap_reason?.trim() ? job.gap_reason.trim() : null;
  const isPartial = state === "partial" || (state === "unknown" && gapCount > 0);
  const isComplete = state === "complete";

  const detail = isPartial
    ? gapReason ?? `${gapCount} batch(es) of records are missing from this output`
    : gapReason;

  return {
    state,
    isPartial,
    isComplete,
    gapCount,
    gapReason,
    label: isPartial ? "partial" : null,
    detail: detail ?? null,
  };
}

/** True when the job produced output that is explicitly incomplete. */
export function isPartial(job: JobLike | null | undefined): boolean {
  return completionOf(job).isPartial;
}

type ProgressJob = {
  status: string;
  completed_chunks?: number | null;
  total_chunks?: number | null;
};

/**
 * Percentage of a job's chunks that are done, 0–100.
 *
 * A completed job is 100% by definition. `total_chunks` is an estimate the
 * worker re-fits as it adapts chunk size, and runs finished before that re-fit
 * still carry the old denominator — that is how a job completed at "13 / 25"
 * (52%). The status is the authority for finished work; in-flight jobs keep the
 * live ratio. Missing/legacy fields and a zero total read as 0%.
 */
export function jobProgress(job: ProgressJob | null | undefined): number {
  if (job?.status === "completed") return 100;
  const total = normalizeCount(job?.total_chunks);
  if (total === 0) return 0;
  const completed = normalizeCount(job?.completed_chunks);
  return Math.min(100, Math.max(0, Math.round((completed / total) * 100)));
}

/** Human-readable summary for a details pane. Empty for ordinary jobs. */
export function gapSummary(job: JobLike | null | undefined): string {
  const info = completionOf(job);
  if (!info.isPartial) return "";
  if (info.gapReason && info.gapCount > 0) {
    return `${info.gapCount} batch(es) incomplete - ${info.gapReason}`;
  }
  if (info.gapReason) return info.gapReason;
  return `${info.gapCount} batch(es) of records were skipped`;
}
