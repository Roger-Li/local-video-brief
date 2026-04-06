import type { JobStatusResponse } from "../types/api";

interface JobStatusCardProps {
  job: JobStatusResponse;
}

export function JobStatusCard({ job }: JobStatusCardProps) {
  return (
    <section className="panel status-panel">
      <div className="status-header">
        <div>
          <span className={`status-pill status-${job.status}`}>{job.status}</span>
          <h2>Job progress</h2>
        </div>
        <code>{job.job_id}</code>
      </div>

      <dl className="status-grid">
        <div>
          <dt>Stage</dt>
          <dd>{job.progress_stage}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{job.provider ?? "pending"}</dd>
        </div>
        <div>
          <dt>Detected language</dt>
          <dd>{job.detected_language ?? "pending"}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{new Date(job.updated_at).toLocaleString()}</dd>
        </div>
      </dl>

      {(job.status === "queued" || job.status === "running") && (
        <div className="progress-bar-track">
          <div className="progress-bar-fill" />
        </div>
      )}

      {job.error ? <p className="error-banner">{job.error}</p> : null}
    </section>
  );
}

