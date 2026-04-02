import { useState } from "react";
import type { JobResultResponse } from "../types/api";
import { StudyGuideView } from "./StudyGuideView";

function formatTimestamp(seconds: number): string {
  const rounded = Math.floor(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  return [hours, minutes, secs].map((value) => value.toString().padStart(2, "0")).join(":");
}

type Tab = "summary" | "study-guide" | "transcript";

interface ResultViewProps {
  result: JobResultResponse;
}

export function ResultView({ result }: ResultViewProps) {
  const hasStudyPack = result.study_pack != null;
  const [activeTab, setActiveTab] = useState<Tab>("summary");

  const tabs: { id: Tab; label: string; hidden?: boolean }[] = [
    { id: "summary", label: "Summary" },
    { id: "study-guide", label: "Study Guide", hidden: !hasStudyPack },
    { id: "transcript", label: "Transcript" },
  ];

  return (
    <section className="results-grid">
      <div className="tab-bar">
        {tabs
          .filter((tab) => !tab.hidden)
          .map((tab) => (
            <button
              key={tab.id}
              className={`tab-button${activeTab === tab.id ? " tab-active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
      </div>

      {activeTab === "summary" && (
        <>
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
        </>
      )}

      {activeTab === "study-guide" && result.study_pack && (
        <article className="panel">
          <StudyGuideView
            studyPack={result.study_pack}
            title={String(result.source_metadata.title ?? "Study Guide")}
          />
        </article>
      )}

      {activeTab === "transcript" && (
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
      )}
    </section>
  );
}
