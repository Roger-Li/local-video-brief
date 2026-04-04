import type { StudyPack } from "../types/api";
import { studyPackToMarkdown, downloadAsFile } from "../lib/export";

function formatTimestamp(seconds: number): string {
  const rounded = Math.floor(seconds);
  const minutes = Math.floor(rounded / 60);
  const secs = rounded % 60;
  return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

interface StudyGuideViewProps {
  studyPack: StudyPack;
  title?: string;
}

export function StudyGuideView({ studyPack, title }: StudyGuideViewProps) {
  const handleExport = () => {
    const markdown = studyPackToMarkdown(studyPack, title);
    const sanitized = (title ?? "").replace(/[^a-zA-Z0-9\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
    const filename = sanitized || "study-guide";
    downloadAsFile(markdown, `${filename}.md`, "text/markdown");
  };

  return (
    <div className="study-guide-panel">
      <div className="export-bar">
        <button className="export-button" onClick={handleExport}>
          Export Markdown
        </button>
      </div>

      {studyPack.learning_objectives.length > 0 && (
        <div>
          <h3>Learning Objectives</h3>
          <ul className="objectives-list">
            {studyPack.learning_objectives.map((obj) => (
              <li key={obj}>{obj}</li>
            ))}
          </ul>
        </div>
      )}

      {studyPack.sections.length > 0 && (
        <div>
          <h3>Sections</h3>
          <div className="chapter-list">
            {studyPack.sections.map((section, idx) => (
              <div className="study-section-card" key={`${section.chapter_index}-${idx}`}>
                <div className="chapter-timing">
                  {formatTimestamp(section.start_s)} – {formatTimestamp(section.end_s)}
                </div>
                <h4>{section.title}</h4>
                <p>{section.summary_en}</p>
                <p className="muted">{section.summary_zh}</p>
                {section.key_points.length > 0 && (
                  <ul>
                    {section.key_points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {studyPack.final_takeaways.length > 0 && (
        <div>
          <h3>Final Takeaways</h3>
          <ul className="takeaways-list">
            {studyPack.final_takeaways.map((ta) => (
              <li key={ta}>{ta}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
