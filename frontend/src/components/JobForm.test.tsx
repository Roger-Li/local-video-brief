import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobForm } from "./JobForm";
import type { ServerConfig } from "../types/api";

const baseConfig: ServerConfig = {
  summarizer_provider: "omlx",
  default_summarizer_provider: "omlx",
  current_model: "qwen2.5",
  model_override_allowed: true,
  supports_prompt_customization: true,
  supports_power_mode: true,
  style_presets: [
    { id: "default", label: "Default", description: "balanced" },
  ],
  available_summarizer_providers: [
    { id: "omlx", label: "Local oMLX", current_model: "qwen2.5", model_override_allowed: true },
    {
      id: "deepseek",
      label: "DeepSeek API",
      current_model: "deepseek-v4-flash",
      model_override_allowed: false,
      model_choices: [
        { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
        { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
      ],
    },
  ],
};

describe("JobForm", () => {
  it("renders form with URL input and submit button", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={false} />);
    expect(screen.getByPlaceholderText(/youtube/i)).toBeInTheDocument();
    expect(screen.getByText("Create summary job")).toBeInTheDocument();
  });

  it("submit button shows pending state", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={true} />);
    expect(screen.getByText("Submitting...")).toBeDisabled();
  });

  it("options panel is collapsed by default", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={false} />);
    expect(screen.getByText("Options")).toBeInTheDocument();
    expect(screen.queryByText("Generate study guide")).not.toBeInTheDocument();
  });

  it("expands options on click", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={false} />);
    fireEvent.click(screen.getByText("Options"));
    expect(screen.getByText("Generate study guide")).toBeInTheDocument();
    expect(screen.getByText("Normalize transcript")).toBeInTheDocument();
  });

  it("submits without options when panel not expanded", () => {
    const onSubmit = vi.fn();
    const { container } = render(<JobForm onSubmit={onSubmit} isPending={false} />);
    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        urls: ["https://www.youtube.com/watch?v=test"],
        options: undefined,
      }),
    );
  });

  it("submits multiple urls one per line", () => {
    const onSubmit = vi.fn();
    const { container } = render(<JobForm onSubmit={onSubmit} isPending={false} />);
    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, {
      target: { value: "https://www.youtube.com/watch?v=one\nhttps://youtu.be/two" },
    });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        urls: ["https://www.youtube.com/watch?v=one", "https://youtu.be/two"],
      }),
    );
  });

  it("ignores blank lines and trims whitespace", () => {
    const onSubmit = vi.fn();
    const { container } = render(<JobForm onSubmit={onSubmit} isPending={false} />);
    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, {
      target: { value: "  https://www.youtube.com/watch?v=one  \n\n\n https://youtu.be/two\n" },
    });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        urls: ["https://www.youtube.com/watch?v=one", "https://youtu.be/two"],
      }),
    );
  });

  it("rejects non-http lines with inline error and does not submit", () => {
    const onSubmit = vi.fn();
    const { container } = render(<JobForm onSubmit={onSubmit} isPending={false} />);
    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, {
      target: { value: "https://www.youtube.com/watch?v=one\nnot-a-url" },
    });
    fireEvent.submit(container.querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/not a valid url/i)).toBeInTheDocument();
  });

  it("button label pluralizes for multiple urls", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={false} />);
    const input = screen.getByPlaceholderText(/youtube/i);
    expect(screen.getByText("Create summary job")).toBeInTheDocument();
    fireEvent.change(input, {
      target: { value: "https://a.example/1\nhttps://b.example/2\nhttps://c.example/3" },
    });
    expect(screen.getByText("Create 3 summary jobs")).toBeInTheDocument();
  });

  it("submits with study pack enabled", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} />);

    // Expand options
    fireEvent.click(screen.getByText("Options"));

    // Toggle study pack on
    const checkboxes = screen.getAllByRole("checkbox");
    const studyPackCheckbox = checkboxes[0]; // Generate study guide
    fireEvent.click(studyPackCheckbox);

    // Fill URL and submit
    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        options: { enable_study_pack: true },
      }),
    );
  });

  it("expanded panel with untouched toggles sends no options", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} />);

    // Expand options but don't touch any toggles — both remain null (server default)
    fireEvent.click(screen.getByText("Options"));

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        options: undefined,
      }),
    );
  });

  it("submits with normalization disabled", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} />);

    fireEvent.click(screen.getByText("Options"));

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]); // uncheck normalization

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        options: { enable_transcript_normalization: false },
      }),
    );
  });

  it("renders provider selector when multiple providers are available", () => {
    render(<JobForm onSubmit={vi.fn()} isPending={false} serverConfig={baseConfig} />);
    fireEvent.click(screen.getByText("Options"));
    expect(screen.getByText("Local oMLX")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek API")).toBeInTheDocument();
  });

  it("local oMLX selected (default) does not send provider override or deepseek_model", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} serverConfig={baseConfig} />);
    fireEvent.click(screen.getByText("Options"));

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const call = onSubmit.mock.calls[0][0];
    expect(call.options).toBeUndefined();
  });

  it("submits provider override and deepseek_model when DeepSeek is selected", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} serverConfig={baseConfig} />);
    fireEvent.click(screen.getByText("Options"));

    fireEvent.click(screen.getByText("DeepSeek API"));

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    const call = onSubmit.mock.calls[0][0];
    expect(call.options).toEqual({
      summarizer_provider_override: "deepseek",
      deepseek_model: "deepseek-v4-flash",
    });
  });

  it("submits deepseek_model when DeepSeek is the server default and dropdown changes", () => {
    const onSubmit = vi.fn();
    const deepseekDefault: ServerConfig = {
      ...baseConfig,
      summarizer_provider: "deepseek",
      default_summarizer_provider: "deepseek",
      current_model: "deepseek-v4-flash",
      model_override_allowed: false,
    };
    render(<JobForm onSubmit={onSubmit} isPending={false} serverConfig={deepseekDefault} />);
    fireEvent.click(screen.getByText("Options"));

    // Don't click any provider pill — DeepSeek is already the default.
    fireEvent.change(screen.getByLabelText("DeepSeek model"), {
      target: { value: "deepseek-v4-pro" },
    });

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    const call = onSubmit.mock.calls[0][0];
    // No override (DeepSeek matches default) but deepseek_model must be sent.
    expect(call.options).toEqual({ deepseek_model: "deepseek-v4-pro" });
  });

  it("DeepSeek-default, untouched dropdown sends no options", () => {
    const onSubmit = vi.fn();
    const deepseekDefault: ServerConfig = {
      ...baseConfig,
      summarizer_provider: "deepseek",
      default_summarizer_provider: "deepseek",
    };
    render(<JobForm onSubmit={onSubmit} isPending={false} serverConfig={deepseekDefault} />);
    fireEvent.click(screen.getByText("Options"));

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    expect(onSubmit.mock.calls[0][0].options).toBeUndefined();
  });

  it("submits DeepSeek Pro when the model dropdown is changed", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} serverConfig={baseConfig} />);
    fireEvent.click(screen.getByText("Options"));

    fireEvent.click(screen.getByText("DeepSeek API"));
    fireEvent.change(screen.getByLabelText("DeepSeek model"), {
      target: { value: "deepseek-v4-pro" },
    });

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    const call = onSubmit.mock.calls[0][0];
    expect(call.options).toEqual({
      summarizer_provider_override: "deepseek",
      deepseek_model: "deepseek-v4-pro",
    });
  });
});
