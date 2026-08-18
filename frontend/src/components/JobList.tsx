import { useEffect, useState } from "react";
import type { JobStatusResponse } from "../types/api";

const JOBS_PER_PAGE = 8;

interface JobListProps {
  jobs: JobStatusResponse[];
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

export function JobList({ jobs, selectedJobId, onSelect }: JobListProps) {
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(1, Math.ceil(jobs.length / JOBS_PER_PAGE));
  const currentPageIndex = Math.min(pageIndex, pageCount - 1);

  useEffect(() => {
    setPageIndex((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  useEffect(() => {
    if (!selectedJobId) return;
    const selectedIndex = jobs.findIndex((job) => job.job_id === selectedJobId);
    if (selectedIndex >= 0) {
      setPageIndex(Math.floor(selectedIndex / JOBS_PER_PAGE));
    }
  }, [jobs, selectedJobId]);

  if (jobs.length === 0) {
    return null;
  }

  const firstJobIndex = currentPageIndex * JOBS_PER_PAGE;
  const visibleJobs = jobs.slice(firstJobIndex, firstJobIndex + JOBS_PER_PAGE);
  const firstVisibleNumber = firstJobIndex + 1;
  const lastVisibleNumber = firstJobIndex + visibleJobs.length;

  return (
    <section className="panel job-list-panel" aria-labelledby="jobs-heading">
      <header className="job-list-header">
        <div>
          <h2 id="jobs-heading">Jobs</h2>
          <p>Recent processing history</p>
        </div>
        <span className="job-list-count">
          {jobs.length} {jobs.length === 1 ? "job" : "jobs"}
        </span>
      </header>

      <div className="job-list" key={currentPageIndex}>
        {visibleJobs.map((job) => (
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

      {pageCount > 1 ? (
        <footer className="job-pagination" aria-label="Jobs pagination">
          <span className="job-page-range">
            {firstVisibleNumber}–{lastVisibleNumber} of {jobs.length}
          </span>
          <div className="job-page-controls">
            <button
              type="button"
              className="job-page-button"
              onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
              disabled={currentPageIndex === 0}
              aria-label="Previous jobs page"
            >
              <span aria-hidden="true">←</span>
              Previous
            </button>
            <span className="job-page-indicator" aria-live="polite">
              Page <strong>{currentPageIndex + 1}</strong> of {pageCount}
            </span>
            <button
              type="button"
              className="job-page-button"
              onClick={() =>
                setPageIndex((current) => Math.min(pageCount - 1, current + 1))
              }
              disabled={currentPageIndex === pageCount - 1}
              aria-label="Next jobs page"
            >
              Next
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </footer>
      ) : null}
    </section>
  );
}
