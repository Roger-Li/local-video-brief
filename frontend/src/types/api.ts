export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface CreateJobRequest {
  url: string;
  output_languages?: string[];
  mode?: "captions_first";
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
}

export interface JobStatusResponse {
  job_id: string;
  url: string;
  status: JobStatus;
  progress_stage: string;
  provider?: string | null;
  detected_language?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TranscriptSegment {
  start_s: number;
  end_s: number;
  text: string;
  language: string;
  source: string;
  confidence?: number | null;
}

export interface ChapterSummary {
  start_s: number;
  end_s: number;
  title: string;
  summary_en: string;
  summary_zh: string;
  key_points: string[];
}

export interface OverallSummary {
  summary_en: string;
  summary_zh: string;
  highlights: string[];
}

export interface JobResultResponse {
  job_id: string;
  status: JobStatus;
  source_metadata: Record<string, unknown>;
  transcript_segments: TranscriptSegment[];
  chapters: ChapterSummary[];
  overall_summary: OverallSummary;
  artifacts: Record<string, unknown>;
}

