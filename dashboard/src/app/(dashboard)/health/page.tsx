import { createClient } from "@/lib/supabase/server";
import { computeJobHealth, type JobRunRow } from "@/lib/jobs";
import { formatAge, formatDateTime } from "@/lib/format";

export default async function HealthPage() {
  const supabase = await createClient();
  const { data: jobRuns } = await supabase.from("job_runs").select("*");
  const health = computeJobHealth((jobRuns as JobRunRow[]) ?? []);

  return (
    <section className="panel">
      <h2>Kesehatan sistem</h2>
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Status</th>
            <th>Terakhir sukses</th>
            <th>Umur data</th>
            <th>Error terbaru</th>
          </tr>
        </thead>
        <tbody>
          {health.map((h) => (
            <tr key={h.job_name}>
              <td>{h.job_name}</td>
              <td>
                <span className={`badge ${h.stale ? "stale" : "ok"}`}>
                  {h.stale ? "basi" : "segar"}
                </span>{" "}
                {h.status}
              </td>
              <td>{formatDateTime(h.last_success_at)}</td>
              <td>{formatAge(h.age_seconds)}</td>
              <td>{h.last_error ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
