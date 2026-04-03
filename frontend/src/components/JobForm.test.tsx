import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { JobForm } from "./JobForm";

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
        url: "https://www.youtube.com/watch?v=test",
        options: undefined,
      }),
    );
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
        options: { enable_study_pack: true, enable_transcript_normalization: true },
      }),
    );
  });

  it("expanded panel with defaults sends explicit false/true", () => {
    const onSubmit = vi.fn();
    render(<JobForm onSubmit={onSubmit} isPending={false} />);

    // Expand options but don't touch any toggles
    fireEvent.click(screen.getByText("Options"));

    const input = screen.getByPlaceholderText(/youtube/i);
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=test" } });
    fireEvent.submit(input.closest("form")!);

    // Both explicit: study pack off, normalization on
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        options: { enable_study_pack: false, enable_transcript_normalization: true },
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
        options: { enable_study_pack: false, enable_transcript_normalization: false },
      }),
    );
  });
});
