import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5173" },
  webServer: [
    {
      command: ".venv/bin/python tests/browser/serve_fake_ui.py",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
});
