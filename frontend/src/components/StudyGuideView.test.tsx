import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StudyGuideView } from "./StudyGuideView";
import type { StudyPack } from "../types/api";

const studyPack: StudyPack = {
  version: 1,
  format: "lecture_study_guide",
  learning_objectives: ["Objective A", "Objective B"],
  sections: [
    {
      chapter_index: 0,
      start_s: 0,
      end_s: 600,
      title: "First Section",
      summary_en: "English summary",
      summary_zh: "中文摘要",
      key_points: ["Key point 1", "Key point 2"],
    },
    {
      chapter_index: 1,
      start_s: 600,
      end_s: 1200,
      title: "Second Section",
      summary_en: "More content",
      summary_zh: "更多内容",
      key_points: [],
    },
  ],
  final_takeaways: ["Takeaway X"],
};

describe("StudyGuideView", () => {
  it("renders learning objectives", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    expect(screen.getByText("Objective A")).toBeInTheDocument();
    expect(screen.getByText("Objective B")).toBeInTheDocument();
  });

  it("renders sections with bilingual summaries", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    expect(screen.getByText("First Section")).toBeInTheDocument();
    expect(screen.getByText("English summary")).toBeInTheDocument();
    expect(screen.getByText("中文摘要")).toBeInTheDocument();
  });

  it("renders key points when present", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    expect(screen.getByText("Key point 1")).toBeInTheDocument();
    expect(screen.getByText("Key point 2")).toBeInTheDocument();
  });

  it("renders final takeaways", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    expect(screen.getByText("Takeaway X")).toBeInTheDocument();
  });

  it("renders timestamps in MM:SS format", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    // 0s -> 00:00, 600s -> 10:00 (10:00 appears in both sections)
    expect(screen.getByText(/00:00/)).toBeInTheDocument();
    expect(screen.getAllByText(/10:00/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders export button", () => {
    render(<StudyGuideView studyPack={studyPack} />);
    expect(screen.getByText("Export Markdown")).toBeInTheDocument();
  });

  it("export button triggers download", () => {
    // Mock URL.createObjectURL and revokeObjectURL
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    globalThis.URL.createObjectURL = createObjectURL;
    globalThis.URL.revokeObjectURL = revokeObjectURL;

    render(<StudyGuideView studyPack={studyPack} title="My Guide" />);
    fireEvent.click(screen.getByText("Export Markdown"));

    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
  });
});
