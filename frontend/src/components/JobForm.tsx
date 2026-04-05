import { useState } from "react";
import type { JobOptions, ServerConfig } from "../types/api";

interface JobFormProps {
  onSubmit: (payload: { url: string; output_languages: string[]; mode: "captions_first"; options?: JobOptions }) => void;
  isPending: boolean;
  serverConfig?: ServerConfig;
}

export function JobForm({ onSubmit, isPending, serverConfig }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [enableStudyPack, setEnableStudyPack] = useState<boolean | null>(null);
  const [enableNormalization, setEnableNormalization] = useState<boolean | null>(null);
  const [stylePreset, setStylePreset] = useState<string | null>(null);
  const [focusHint, setFocusHint] = useState("");
  const [modelOverride, setModelOverride] = useState("");

  const supportsPrompts = serverConfig?.supports_prompt_customization ?? false;
  const allowModelOverride = serverConfig?.model_override_allowed ?? false;

  const buildOptions = (): JobOptions | undefined => {
    if (!showOptions) return undefined;
    const opts: JobOptions = {};
    if (enableStudyPack !== null) opts.enable_study_pack = enableStudyPack;
    if (enableNormalization !== null) opts.enable_transcript_normalization = enableNormalization;
    if (supportsPrompts) {
      if (stylePreset !== null) opts.style_preset = stylePreset;
      if (focusHint.trim()) opts.focus_hint = focusHint.trim();
      if (modelOverride.trim()) opts.omlx_model_override = modelOverride.trim();
    }
    return Object.keys(opts).length > 0 ? opts : undefined;
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

          {supportsPrompts && (
            <>
              <div className="options-section-label">Summarization</div>

              <div className="preset-row">
                {(serverConfig?.style_presets ?? []).map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`preset-pill ${
                      (stylePreset === null && p.id === "default") || stylePreset === p.id
                        ? "preset-pill-active"
                        : ""
                    }`}
                    title={p.description}
                    onClick={() => setStylePreset(p.id === "default" ? null : p.id)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              <div className="focus-hint-field">
                <label className="field">
                  <span>Content focus</span>
                  <textarea
                    placeholder="E.g., Emphasize the mathematical proofs and derivations..."
                    value={focusHint}
                    onChange={(e) => {
                      if (e.target.value.length <= 500) setFocusHint(e.target.value);
                    }}
                  />
                </label>
                <span className="char-count">{focusHint.length} / 500</span>
              </div>

              {allowModelOverride && (
                <label className="field model-override-field">
                  <span>Model override</span>
                  <input
                    type="text"
                    placeholder={serverConfig?.current_model ?? "model name"}
                    value={modelOverride}
                    onChange={(e) => setModelOverride(e.target.value)}
                  />
                </label>
              )}
            </>
          )}
        </div>
      )}

      <button className="primary-button" type="submit" disabled={isPending}>
        {isPending ? "Submitting..." : "Create summary job"}
      </button>
    </form>
  );
}
