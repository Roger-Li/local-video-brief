import type { StudyPack } from "../types/api";

function formatTimestamp(seconds: number): string {
  const rounded = Math.floor(seconds);
  const minutes = Math.floor(rounded / 60);
  const secs = rounded % 60;
  return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

export function studyPackToMarkdown(studyPack: StudyPack, title?: string): string {
  const lines: string[] = [];

  lines.push(`# ${title ?? "Study Guide"}`);
  lines.push("");

  if (studyPack.learning_objectives.length > 0) {
    lines.push("## Learning Objectives");
    lines.push("");
    for (const obj of studyPack.learning_objectives) {
      lines.push(`- ${obj}`);
    }
    lines.push("");
  }

  if (studyPack.sections.length > 0) {
    lines.push("## Sections");
    lines.push("");
    for (const section of studyPack.sections) {
      const timeRange = `[${formatTimestamp(section.start_s)}\u2013${formatTimestamp(section.end_s)}]`;
      lines.push(`### ${section.title} ${timeRange}`);
      lines.push("");
      if (section.summary_en) {
        lines.push(section.summary_en);
        lines.push("");
      }
      if (section.summary_zh) {
        lines.push(section.summary_zh);
        lines.push("");
      }
      if (section.key_points.length > 0) {
        lines.push("**Key Points:**");
        lines.push("");
        for (const kp of section.key_points) {
          lines.push(`- ${kp}`);
        }
        lines.push("");
      }
    }
  }

  if (studyPack.final_takeaways.length > 0) {
    lines.push("## Final Takeaways");
    lines.push("");
    for (const ta of studyPack.final_takeaways) {
      lines.push(`- ${ta}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

export function downloadAsFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
