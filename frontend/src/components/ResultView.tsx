import type { JobResultResponse } from "../types/api";

function formatTimestamp(seconds: number): string {
  const rounded = Math.floor(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  return [hours, minutes, secs].map((value) => value.toString().padStart(2, "0")).join(":");
}

interface ResultViewProps {
  result: JobResultResponse;
}

export function ResultView({ result }: ResultViewProps) {
  return (
    <section className="results-grid">
      <article className="panel">
        <span className="eyebrow">Overall summary</span>
        <h2>{String(result.source_metadata.title ?? "Untitled video")}</h2>
        <div className="summary-block">
          <h3>English</h3>
          <p>{result.overall_summary.summary_en}</p>
        </div>
        <div className="summary-block">
          <h3>中文</h3>
          <p>{result.overall_summary.summary_zh}</p>
        </div>
        <div className="highlight-list">
          {result.overall_summary.highlights.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </article>

      <article className="panel">
        <span className="eyebrow">Chapters</span>
        <div className="chapter-list">
          {result.chapters.map((chapter) => (
            <div className="chapter-card" key={`${chapter.start_s}-${chapter.end_s}`}>
              <div className="chapter-timing">
                {formatTimestamp(chapter.start_s)} - {formatTimestamp(chapter.end_s)}
              </div>
              <h3>{chapter.title}</h3>
              <p>{chapter.summary_en}</p>
              <p className="muted">{chapter.summary_zh}</p>
              <ul>
                {chapter.key_points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </article>

      <article className="panel transcript-panel">
        <span className="eyebrow">Transcript</span>
        <div className="transcript-list">
          {result.transcript_segments.map((segment) => (
            <div key={`${segment.start_s}-${segment.end_s}`} className="transcript-row">
              <span>{formatTimestamp(segment.start_s)}</span>
              <p>{segment.text}</p>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

