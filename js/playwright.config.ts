import { defineConfig, devices } from "@playwright/test";

/**
 * The example search bar, built and served as it ships, in every engine and on two phones.
 * Desktop projects drive it with a keyboard, the phones with taps.
 */
export default defineConfig({
  testDir: "e2e",
  outputDir: ".scratch/test-results",
  reporter: [["list"], ["html", { open: "never", outputFolder: ".scratch/playwright-report" }]],
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  workers: process.env["CI"] ? 2 : 4,
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "pnpm vite build examples/search-bar && pnpm vite preview examples/search-bar",
    url: "http://localhost:4173",
    // Never reuse: a server left running serves an old build, and the run tests stale code.
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, grepInvert: /@touch/u },
    { name: "firefox", use: { ...devices["Desktop Firefox"] }, grepInvert: /@touch/u },
    { name: "webkit", use: { ...devices["Desktop Safari"] }, grepInvert: /@touch/u },
    { name: "phone-chromium", use: { ...devices["Pixel 7"] }, grepInvert: /@keyboard/u },
    { name: "phone-webkit", use: { ...devices["iPhone 15"] }, grepInvert: /@keyboard/u },
  ],
});
