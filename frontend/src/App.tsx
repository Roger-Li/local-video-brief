import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createJob, getConfig, getJobResult, listJobs } from "./lib/api";
import { JobForm } from "./components/JobForm";
import { JobList } from "./components/JobList";
import { JobStatusCard } from "./components/JobStatusCard";
import { ResultView } from "./components/ResultView";
import type { JobOptions } from "./types/api";

interface BatchSubmitPayload {
  urls: string[];
  output_languages: string[];
  mode: "captions_first";
  options?: JobOptions;
}

interface BatchSubmitResult {
  createdJobIds: string[];
  failures: { url: string; message: string }[];
}

export default function App() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: Infinity,
  });

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: () => listJobs(),
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      return jobs.some((job) => job.status === "queued" || job.status === "running")
        ? 2500
        : false;
    },
  });

  const createJobsMutation = useMutation({
    mutationFn: async ({ urls, ...rest }: BatchSubmitPayload): Promise<BatchSubmitResult> => {
      // allSettled so one bad URL doesn't discard sibling submissions.
      const settled = await Promise.allSettled(urls.map((url) => createJob({ url, ...rest })));
      const createdJobIds: string[] = [];
      const failures: { url: string; message: string }[] = [];
      settled.forEach((outcome, index) => {
        if (outcome.status === "fulfilled") {
          createdJobIds.push(outcome.value.job_id);
        } else {
          failures.push({
            url: urls[index],
            message: outcome.reason instanceof Error ? outcome.reason.message : String(outcome.reason),
          });
        }
      });
      return { createdJobIds, failures };
    },
    onSuccess: ({ createdJobIds }) => {
      // Restarts the jobs poll, which stops once no job is active.
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      if (createdJobIds.length > 0) {
        setSelectedJobId(createdJobIds[0]);
      }
    },
  });

  const jobs = jobsQuery.data?.jobs ?? [];
  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) ?? null;
  const submitFailures = createJobsMutation.data?.failures ?? [];

  const resultQuery = useQuery({
    queryKey: ["job-result", selectedJobId],
    queryFn: () => getJobResult(selectedJobId!),
    enabled: selectedJob?.status === "completed",
    staleTime: Infinity,
  });

  return (
    <main className="app-shell">
      <div className="hero-background" />
      <section className="content-stack">
        <JobForm
          onSubmit={(payload) => createJobsMutation.mutate(payload)}
          isPending={createJobsMutation.isPending}
          serverConfig={configQuery.data}
        />

        {createJobsMutation.isError ? (
          <p className="error-banner">{(createJobsMutation.error as Error).message}</p>
        ) : null}
        {submitFailures.map((failure) => (
          <p className="error-banner" key={failure.url}>
            Failed to submit {failure.url}: {failure.message}
          </p>
        ))}

        <JobList jobs={jobs} selectedJobId={selectedJobId} onSelect={setSelectedJobId} />
        {jobsQuery.isError ? <p className="error-banner">{(jobsQuery.error as Error).message}</p> : null}

        {selectedJob ? <JobStatusCard job={selectedJob} /> : null}

        {selectedJob?.status === "completed" && resultQuery.data ? (
          <ResultView result={resultQuery.data} />
        ) : null}
        {resultQuery.isError ? <p className="error-banner">{(resultQuery.error as Error).message}</p> : null}
      </section>
    </main>
  );
}
