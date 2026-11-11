// Mirrors src/jobs.py: JOB_INTERVALS_SECONDS and run_health_check. Keep these
// two in sync by hand if a job's schedule changes on the bot side.
export const JOB_INTERVALS_SECONDS: Record<string, number> = {
  job0_universe: 86_400,
  job1_market_snapshot: 3_600,
  job2_derivatives_pulse: 900,
  job5_news: 900,
  job7_macro: 86_400,
  job10_events: 86_400,
  job11_account: 60,
  job12_signal_outcomes: 3_600,
};

export type JobRunRow = {
  job_name: string;
  status: "ok" | "error";
  last_success_at: string | null;
  last_error: string | null;
  updated_at: string;
};

export type JobHealth = {
  job_name: string;
  status: "ok" | "error" | "never_run";
  last_success_at: string | null;
  last_error: string | null;
  age_seconds: number | null;
  stale: boolean;
};

// Same rule as run_health_check: stale if last success is older than 2x the
// job's expected interval, or if it has never run.
export function computeJobHealth(
  runs: JobRunRow[],
  now: Date = new Date(),
): JobHealth[] {
  const byName = new Map(runs.map((r) => [r.job_name, r]));
  return Object.entries(JOB_INTERVALS_SECONDS).map(([job_name, intervalS]) => {
    const run = byName.get(job_name);
    const lastSuccessAt = run?.last_success_at ?? null;
    const ageSeconds = lastSuccessAt
      ? (now.getTime() - new Date(lastSuccessAt).getTime()) / 1000
      : null;
    const stale = ageSeconds === null || ageSeconds > 2 * intervalS;
    return {
      job_name,
      status: run ? run.status : "never_run",
      last_success_at: lastSuccessAt,
      last_error: run?.last_error ?? null,
      age_seconds: ageSeconds,
      stale,
    };
  });
}
