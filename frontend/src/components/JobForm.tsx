import { useState } from "react";
import type { JobOptions } from "../types/api";

interface JobFormProps {
  onSubmit: (payload: { url: string; output_languages: string[]; mode: "captions_first"; options?: JobOptions }) => void;
  isPending: boolean;
}

export function JobForm({ onSubmit, isPending }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [enableStudyPack, setEnableStudyPack] = useState<boolean | null>(null);
  const [enableNormalization, setEnableNormalization] = useState<boolean | null>(null);

  const buildOptions = (): JobOptions | undefined => {
    if (!showOptions) return undefined;
    // When the options panel is expanded, always send explicit values
    // so the visual toggle state matches the actual behavior.
    return {
      enable_study_pack: enableStudyPack === true,
      enable_transcript_normalization: enableNormalization !== false,
    };
  };

  return (
    <form
      className="panel form-panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          url,
          output_languages: ["en", "zh-CN"],
          mode: "captions_first",
          options: buildOptions(),
        });
      }}
    >
      <div className="form-copy">
        <span className="eyebrow">Local-first summarization</span>
        <h1>Summarize videos on your Mac with open models.</h1>
        <p>
          Paste a YouTube, bilibili, or other <code>yt-dlp</code>-supported URL. The app prefers captions, falls
          back to local ASR, and produces bilingual English/Chinese chapter summaries.
        </p>
      </div>

      <label className="field">
        <span>Video URL</span>
        <input
          type="url"
          placeholder="https://www.youtube.com/watch?v=..."
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
      </label>

      <button
        type="button"
        className="options-toggle"
        onClick={() => setShowOptions(!showOptions)}
      >
        {showOptions ? "Hide options" : "Options"}
      </button>

      {showOptions && (
        <div className="options-panel">
          <label className="toggle-row">
            <span>Generate study guide</span>
            <input
              type="checkbox"
              className="toggle-switch"
              checked={enableStudyPack === true}
              onChange={(e) => setEnableStudyPack(e.target.checked)}
            />
          </label>
          <label className="toggle-row">
            <span>Normalize transcript</span>
            <input
              type="checkbox"
              className="toggle-switch"
              checked={enableNormalization !== false}
              onChange={(e) => setEnableNormalization(e.target.checked)}
            />
          </label>
        </div>
      )}

      <button className="primary-button" type="submit" disabled={isPending}>
        {isPending ? "Submitting..." : "Create summary job"}
      </button>
    </form>
  );
}

