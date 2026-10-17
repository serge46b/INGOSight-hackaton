import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 180000,
  workers: 1,
  fullyParallel: false,
  expect: { timeout: 15000 },
  use: {
    baseURL: process.env.BASE_URL || "http://GPUnStorageServer.local:18080",
    ...devices["Desktop Chrome"],
    permissions: ["clipboard-read", "clipboard-write"],
  },
});
