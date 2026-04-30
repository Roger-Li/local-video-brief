import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AvailableProviderInfo,
  DeepseekModelId,
  JobOptions,
  ServerConfig,
  SummarizerProviderId,
} from "../types/api";
import { getPowerPromptDefault } from "../lib/api";

interface JobFormProps {
  onSubmit: (payload: { url: string; output_languages: string[]; mode: "captions_first"; options?: JobOptions }) => void;
  isPending: boolean;
  serverConfig?: ServerConfig;
}

const DEFAULT_DEEPSEEK_MODEL: DeepseekModelId = "deepseek-v4-flash";

export function JobForm({ onSubmit, isPending, serverConfig }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [enableStudyPack, setEnableStudyPack] = useState<boolean | null>(null);
  const [enableNormalization, setEnableNormalization] = useState<boolean | null>(null);
  const [stylePreset, setStylePreset] = useState<string | null>(null);
  const [focusHint, setFocusHint] = useState("");
  const [modelOverride, setModelOverride] = useState("");
  const [powerMode, setPowerMode] = useState(false);
  const [powerPrompt, setPowerPrompt] = useState("");
  const [powerPromptDirty, setPowerPromptDirty] = useState(false);
  const [strategyOverride, setStrategyOverride] = useState<"auto" | "force_single_shot">("auto");
  const [providerSelection, setProviderSelection] = useState<SummarizerProviderId | null>(null);
  const [deepseekModel, setDeepseekModel] = useState<DeepseekModelId>(DEFAULT_DEEPSEEK_MODEL);
  const [deepseekModelTouched, setDeepseekModelTouched] = useState(false);

  const supportsPrompts = serverConfig?.supports_prompt_customization ?? false;
  const supportsPowerMode = serverConfig?.supports_power_mode ?? false;

  const availableProviders: AvailableProviderInfo[] = serverConfig?.available_summarizer_providers ?? [];
  const defaultProvider = (serverConfig?.default_summarizer_provider ?? null) as SummarizerProviderId | null;
  const showProviderSelector = availableProviders.length >= 2;
  const activeProviderId: SummarizerProviderId | null =
    providerSelection ?? (defaultProvider as SummarizerProviderId | null);
  const activeProvider = availableProviders.find((p) => p.id === activeProviderId) ?? null;
  const allowModelOverride =
    activeProvider?.model_override_allowed ?? (serverConfig?.model_override_allowed ?? false);
  const isDeepseek = activeProviderId === "deepseek";

  // Counter guards against stale fetch responses overwriting user edits.
  const fetchIdRef = useRef(0);
  // Track previous guided state to distinguish real changes from initial mount.
  const prevGuidedRef = useRef({ stylePreset, focusHint });

  const fetchDefaultBrief = useCallback(async () => {
    const id = ++fetchIdRef.current;
    try {
      const brief = await getPowerPromptDefault(stylePreset, focusHint || undefined);
      // Only apply if this is still the latest fetch request.
      if (fetchIdRef.current === id) {
        setPowerPrompt(brief);
        setPowerPromptDirty(false);
      }
    } catch {
      // Silently ignore — user can still type manually.
    }
  }, [stylePreset, focusHint]);

  // Re-fetch default brief when guided controls change while in power mode.
  // Handles both the clean case (silently re-fetch) and the dirty case
  // (prompt to confirm reset). Runs after React has committed state updates
  // so it always sees the current stylePreset/focusHint values.
  useEffect(() => {
    if (!powerMode) return;
    const prev = prevGuidedRef.current;
    const changed = prev.stylePreset !== stylePreset || prev.focusHint !== focusHint;
    prevGuidedRef.current = { stylePreset, focusHint };
    if (!changed) return; // Initial mount or unrelated re-render — skip.
    if (powerPromptDirty) {
      if (window.confirm("Reset brief to match guided settings?")) {
        fetchDefaultBrief();
      }
      return;
    }
    fetchDefaultBrief();
  }, [stylePreset, focusHint, powerMode, powerPromptDirty, fetchDefaultBrief]);

  const buildOptions = (): JobOptions | undefined => {
    if (!showOptions) return undefined;
    const opts: JobOptions = {};
    if (enableStudyPack !== null) opts.enable_study_pack = enableStudyPack;
    if (enableNormalization !== null) opts.enable_transcript_normalization = enableNormalization;
    if (supportsPrompts) {
      if (stylePreset !== null) opts.style_preset = stylePreset;
      if (focusHint.trim()) opts.focus_hint = focusHint.trim();
      if (allowModelOverride && modelOverride.trim()) {
        opts.omlx_model_override = modelOverride.trim();
      }
    }
    if (providerSelection !== null && defaultProvider !== null && providerSelection !== defaultProvider) {
      opts.summarizer_provider_override = providerSelection;
    }
    if (isDeepseek && (providerSelection === "deepseek" || deepseekModelTouched)) {
      opts.deepseek_model = deepseekModel;
    }
    if (powerMode && supportsPowerMode) {
      opts.power_mode = true;
      if (powerPrompt.trim()) opts.power_prompt = powerPrompt.trim();
      if (strategyOverride !== "auto") opts.strategy_override = strategyOverride;
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

              {showProviderSelector && (
                <div className="provider-row">
                  {availableProviders.map((provider) => {
                    const checked = activeProviderId === provider.id;
                    return (
                      <button
                        key={provider.id}
                        type="button"
                        className={`provider-pill ${checked ? "provider-pill-active" : ""}`}
                        onClick={() => setProviderSelection(provider.id)}
                      >
                        {provider.label}
                      </button>
                    );
                  })}
                </div>
              )}

              {isDeepseek && activeProvider?.model_choices && (
                <label className="field deepseek-model-field">
                  <span>DeepSeek model</span>
                  <select
                    value={deepseekModel}
                    onChange={(e) => {
                      setDeepseekModel(e.target.value as DeepseekModelId);
                      setDeepseekModelTouched(true);
                    }}
                  >
                    {activeProvider.model_choices.map((choice) => (
                      <option key={choice.id} value={choice.id}>
                        {choice.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}

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

              {supportsPowerMode && (
                <>
                  <div className="options-section-label">Mode</div>
                  <div className="mode-toggle-row">
                    <button
                      type="button"
                      className={`mode-pill ${!powerMode ? "mode-pill-active" : ""}`}
                      onClick={() => setPowerMode(false)}
                    >
                      Guided
                    </button>
                    <button
                      type="button"
                      className={`mode-pill ${powerMode ? "mode-pill-active" : ""}`}
                      onClick={() => {
                        setPowerMode(true);
                        if (!powerPrompt) fetchDefaultBrief();
                      }}
                    >
                      Power
                    </button>
                  </div>

                  {powerMode && (
                    <div className="power-panel">
                      <div className="strategy-row">
                        <span className="strategy-label">Strategy:</span>
                        <label className="strategy-radio">
                          <input
                            type="radio"
                            name="strategy"
                            checked={strategyOverride === "auto"}
                            onChange={() => setStrategyOverride("auto")}
                          />
                          Auto
                        </label>
                        <label className="strategy-radio">
                          <input
                            type="radio"
                            name="strategy"
                            checked={strategyOverride === "force_single_shot"}
                            onChange={() => setStrategyOverride("force_single_shot")}
                          />
                          Single-shot
                        </label>
                      </div>

                      <div className="power-prompt-field">
                        <label className="field">
                          <span>Summarization prompt</span>
                          <textarea
                            className="power-prompt-textarea"
                            value={powerPrompt}
                            onChange={(e) => {
                              if (e.target.value.length <= 2000) {
                                setPowerPrompt(e.target.value);
                                setPowerPromptDirty(true);
                              }
                            }}
                          />
                        </label>
                        <div className="power-prompt-footer">
                          <span className="char-count">{powerPrompt.length} / 2000</span>
                          <button
                            type="button"
                            className="reset-brief-button"
                            onClick={fetchDefaultBrief}
                          >
                            Reset
                          </button>
                        </div>
                      </div>

                      <p className="power-info">
                        Output will be free-form text. The model's response is displayed as-is (no
                        structured chapter cards).
                      </p>
                    </div>
                  )}
                </>
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
