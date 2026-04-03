import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ResultView } from "./ResultView";
import type { JobResultResponse, StudyPack } from "../types/api";

const baseResult: JobResultResponse = {
  job_id: "test-1",
  status: "completed",
  source_metadata: { title: "Test Video" },
  transcript_segments: [
    { start_s: 0, end_s: 5, text: "Hello world", language: "en", source: "captions" },
  ],
  chapters: [
    {
      start_s: 0,
      end_s: 300,
      title: "Introduction",
      summary_en: "An intro.",
      summary_zh: "一个介绍。",
      key_points: ["Point 1"],
    },
  ],
  overall_summary: {
    summary_en: "Overall EN",
    summary_zh: "Overall ZH",
    highlights: ["Highlight 1"],
  },
  artifacts: {},
};

const studyPack: StudyPack = {
  version: 1,
  format: "lecture_study_guide",
  learning_objectives: ["Learn testing"],
  sections: [
    {
      chapter_index: 0,
      start_s: 0,
      end_s: 300,
      title: "Intro Section",
      summary_en: "Section EN",
      summary_zh: "Section ZH",
      key_points: ["Key 1"],
    },
  ],
  final_takeaways: ["Takeaway 1"],
};

describe("ResultView", () => {
  it("renders Summary tab by default", () => {
    render(<ResultView result={baseResult} />);
    expect(screen.getByText("Overall summary")).toBeInTheDocument();
    expect(screen.getByText("Test Video")).toBeInTheDocument();
  });

  it("shows Summary and Transcript tabs when no study pack", () => {
    render(<ResultView result={baseResult} />);
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("Transcript")).toBeInTheDocument();
    expect(screen.queryByText("Study Guide")).not.toBeInTheDocument();
  });

  it("shows Study Guide tab when study_pack present", () => {
    render(<ResultView result={{ ...baseResult, study_pack: studyPack }} />);
    expect(screen.getByText("Study Guide")).toBeInTheDocument();
  });

  it("switches to Transcript tab", () => {
    render(<ResultView result={baseResult} />);
    fireEvent.click(screen.getByText("Transcript"));
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("switches to Study Guide tab and renders content", () => {
    render(<ResultView result={{ ...baseResult, study_pack: studyPack }} />);
    fireEvent.click(screen.getByText("Study Guide"));
    expect(screen.getByText("Learn testing")).toBeInTheDocument();
    expect(screen.getByText("Takeaway 1")).toBeInTheDocument();
  });

  it("renders chapters in summary tab", () => {
    render(<ResultView result={baseResult} />);
    expect(screen.getByText("Introduction")).toBeInTheDocument();
    expect(screen.getByText("An intro.")).toBeInTheDocument();
    expect(screen.getByText("Point 1")).toBeInTheDocument();
  });

  it("renders highlights", () => {
    render(<ResultView result={baseResult} />);
    expect(screen.getByText("Highlight 1")).toBeInTheDocument();
  });
});
