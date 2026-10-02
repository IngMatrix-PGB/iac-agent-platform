import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "styles.css"), "utf8");

describe("operator design tokens", () => {
  it("defines distinct text-plus-surface pairs for the status roles", () => {
    for (const name of [
      "--color-status-pass-text",
      "--color-status-pass-surface",
      "--color-status-warn-text",
      "--color-status-warn-surface",
      "--color-status-block-text",
      "--color-status-block-surface",
      "--color-status-attention-text",
      "--color-status-attention-surface",
      "--color-status-published-text",
      "--color-status-published-surface",
      "--color-status-neutral-text",
      "--color-status-neutral-surface",
      "--color-status-rejected-text",
      "--color-status-rejected-surface",
      "--color-notice-config-text",
      "--color-notice-config-border",
      "--color-notice-error-text",
      "--color-notice-error-border",
      "--color-notice-conflict-text",
      "--color-notice-conflict-border",
      "--color-notice-missing-text",
      "--color-notice-missing-border",
    ]) {
      expect(css).toContain(name);
    }
    expect(css).toContain(".chip-pass");
    expect(css).toContain(".chip-warn");
    expect(css).toContain(".chip-block");
    expect(css).toContain(".chip-attention");
    expect(css).toContain(".chip-published");
    expect(css).toContain(".chip-neutral");
    expect(css).toContain(".chip-rejected");
    expect(css).toContain(".chip-error");
    expect(css).toContain(".button-primary");
    expect(css).toContain(".button-secondary");
    expect(css).toContain(".notice-config");
    expect(css).toContain(".notice-error");
    expect(css).toContain(".notice-conflict");
    expect(css).toContain(".notice-missing");
    expect(css).toContain(".finding-stack");
    expect(css).toContain("@media (max-width: 40rem)");
  });

  it("does not reuse the pass surface for publication or the block surface for workflow error", () => {
    const block = css.slice(css.indexOf(".chip-block"), css.indexOf(".chip-attention"));
    const published = css.slice(css.indexOf(".chip-published"), css.indexOf(".chip-neutral"));
    const error = css.slice(css.indexOf(".chip-error"), css.indexOf(".chip-error") + 240);
    expect(block).toContain("var(--color-status-block-surface)");
    expect(published).toContain("var(--color-status-published-surface)");
    expect(published).not.toContain("var(--color-status-pass-surface)");
    expect(error).toContain("var(--color-notice-error-border)");
    expect(error).not.toContain("var(--color-status-block-surface)");
  });
});
