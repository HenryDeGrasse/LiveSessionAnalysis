import { defineConfig, devices } from '@playwright/test'

const FRONTEND_PORT = 3100
const BACKEND_PORT = 8100
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: {
    timeout: 20_000,
  },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],
  use: {
    baseURL: FRONTEND_URL,
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    headless: true,
    launchOptions: {
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        '--autoplay-policy=no-user-gesture-required',
      ],
    },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
  webServer: [
    {
      command:
        'cd ../backend && uv run --python 3.11 --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8100',
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: {
        LSA_CORS_ORIGINS: '["http://127.0.0.1:3100"]',
        LSA_SESSION_DATA_DIR: 'data/playwright-sessions',
      },
    },
    {
      command: 'npm run build && npm run start -- --hostname 127.0.0.1 --port 3100',
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 240_000,
      env: {
        NEXT_PUBLIC_API_URL: BACKEND_URL,
        NEXT_PUBLIC_WS_URL: `ws://127.0.0.1:${BACKEND_PORT}`,
        NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI: 'true',
        NEXT_TELEMETRY_DISABLED: '1',
      },
    },
  ],
})
