import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createJob, getJob, getJobResult } from "./lib/api";
import { JobForm } from "./components/JobForm";
import { JobStatusCard } from "./components/JobStatusCard";
import { ResultView } from "./components/ResultView";
import type { CreateJobRequest } from "./types/api";

export default function App() {
  const [jobId, setJobId] = useState<string | null>(null);

  const createJobMutation = useMutation({
    mutationFn: (payload: CreateJobRequest) => createJob(payload),
    onSuccess: (response) => {
      setJobId(response.job_id);
    },
  });

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 2500;
    },
  });

  const resultQuery = useQuery({
    queryKey: ["job-result", jobId],
    queryFn: () => getJobResult(jobId!),
    enabled: jobQuery.data?.status === "completed",
  });

  return (
    <main className="app-shell">
      <div className="hero-background" />
      <section className="content-stack">
        <JobForm onSubmit={(payload) => createJobMutation.mutate(payload)} isPending={createJobMutation.isPending} />

        {createJobMutation.isError ? (
          <p className="error-banner">{(createJobMutation.error as Error).message}</p>
        ) : null}

        {jobQuery.data ? <JobStatusCard job={jobQuery.data} /> : null}
        {jobQuery.isError ? <p className="error-banner">{(jobQuery.error as Error).message}</p> : null}

        {resultQuery.data ? <ResultView result={resultQuery.data} /> : null}
        {resultQuery.isError ? <p className="error-banner">{(resultQuery.error as Error).message}</p> : null}
      </section>
    </main>
  );
}

