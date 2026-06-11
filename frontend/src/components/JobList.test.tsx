import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobList } from "./JobList";
import type { JobStatusResponse } from "../types/api";

function makeJob(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    job_id: "job-1",
    url: "https://www.youtube.com/watch?v=one",
    status: "running",
    progress_stage: "fetching_captions",
    created_at: "2026-06-10T12:00:00+00:00",
    updated_at: "2026-06-10T12:00:05+00:00",
    ...overrides,
  };
}

describe("JobList", () => {
  it("renders one row per job with status pills", () => {
    const jobs = [
      makeJob(),
      makeJob({ job_id: "job-2", url: "https://youtu.be/two", status: "completed", progress_stage: "completed" }),
    ];
    render(<JobList jobs={jobs} selectedJobId={null} onSelect={vi.fn()} />);
    expect(screen.getByText("https://www.youtube.com/watch?v=one")).toBeInTheDocument();
    expect(screen.getByText("https://youtu.be/two")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    // "completed" appears as both status pill and progress stage.
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("invokes onSelect with job id on click", () => {
    const onSelect = vi.fn();
    render(<JobList jobs={[makeJob()]} selectedJobId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("https://www.youtube.com/watch?v=one"));
    expect(onSelect).toHaveBeenCalledWith("job-1");
  });

  it("marks selected row active", () => {
    const jobs = [makeJob(), makeJob({ job_id: "job-2", url: "https://youtu.be/two" })];
    render(<JobList jobs={jobs} selectedJobId="job-2" onSelect={vi.fn()} />);
    const rows = screen.getAllByRole("button");
    expect(rows[0].className).not.toContain("job-row-active");
    expect(rows[1].className).toContain("job-row-active");
  });

  it("renders nothing for empty list", () => {
    const { container } = render(<JobList jobs={[]} selectedJobId={null} onSelect={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });
});
