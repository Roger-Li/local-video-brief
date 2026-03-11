import { useState } from "react";

interface JobFormProps {
  onSubmit: (payload: { url: string; output_languages: string[]; mode: "captions_first" }) => void;
  isPending: boolean;
}

export function JobForm({ onSubmit, isPending }: JobFormProps) {
  const [url, setUrl] = useState("");

  return (
    <form
      className="panel form-panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          url,
          output_languages: ["en", "zh-CN"],
          mode: "captions_first",
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

      <button className="primary-button" type="submit" disabled={isPending}>
        {isPending ? "Submitting..." : "Create summary job"}
      </button>
    </form>
  );
}

