import { describe, it, expect } from "vitest";
import { studyPackToMarkdown } from "./export";
import type { StudyPack } from "../types/api";

const pack: StudyPack = {
  version: 1,
  format: "lecture_study_guide",
  learning_objectives: ["Obj 1"],
  sections: [
    {
      chapter_index: 0,
      start_s: 60,
      end_s: 600,
      title: "Test Section",
      summary_en: "English",
      summary_zh: "中文",
      key_points: ["KP1"],
    },
  ],
  final_takeaways: ["Takeaway"],
};

describe("studyPackToMarkdown", () => {
  it("includes title as heading", () => {
    const md = studyPackToMarkdown(pack, "My Title");
    expect(md).toContain("# My Title");
  });

  it("defaults title to Study Guide", () => {
    const md = studyPackToMarkdown(pack);
    expect(md).toContain("# Study Guide");
  });

  it("includes learning objectives", () => {
    const md = studyPackToMarkdown(pack);
    expect(md).toContain("- Obj 1");
  });

  it("includes section with timestamps", () => {
    const md = studyPackToMarkdown(pack);
    // 60s -> 01:00, 600s -> 10:00
    expect(md).toContain("01:00");
    expect(md).toContain("10:00");
    expect(md).toContain("Test Section");
  });

  it("includes bilingual summaries", () => {
    const md = studyPackToMarkdown(pack);
    expect(md).toContain("English");
    expect(md).toContain("中文");
  });

  it("includes final takeaways", () => {
    const md = studyPackToMarkdown(pack);
    expect(md).toContain("- Takeaway");
  });
});
