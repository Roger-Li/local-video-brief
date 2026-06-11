import type { JobStatusResponse } from "../types/api";

interface JobListProps {
  jobs: JobStatusResponse[];
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

export function JobList({ jobs, selectedJobId, onSelect }: JobListProps) {
  if (jobs.length === 0) {
    return null;
  }

  return (
    <section className="panel job-list-panel">
      <h2>Jobs</h2>
      <div className="job-list">
        {jobs.map((job) => (
          <button
            key={job.job_id}
            type="button"
            className={`job-row ${job.job_id === selectedJobId ? "job-row-active" : ""}`}
            onClick={() => onSelect(job.job_id)}
          >
            <span className={`status-pill status-${job.status}`}>{job.status}</span>
            <span className="job-row-url" title={job.url}>
              {job.url}
            </span>
            <span className="job-row-stage">{job.progress_stage.replace(/_/g, " ")}</span>
            <span className="job-row-time">
              {new Date(job.created_at).toLocaleTimeString()}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
