import { defineConfig, devices } from '@playwright/test'

const FRONTEND_PORT = 3100
const BACKEND_PORT = 8100
const LIVEKIT_PORT = Number(process.env.PW_LIVEKIT_PORT || '7880')
const LIVEKIT_READY_PORT = Number(process.env.PW_LIVEKIT_READY_PORT || '8788')
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
const LIVEKIT_URL = process.env.PW_LIVEKIT_URL || `ws://127.0.0.1:${LIVEKIT_PORT}`
const MEDIA_PROVIDER =
  process.env.PW_MEDIA_PROVIDER === 'custom_webrtc' ? 'custom_webrtc' : 'livekit'

const livekitServerEnv: Record<string, string> = {
  PW_LIVEKIT_HOST: '127.0.0.1',
  PW_LIVEKIT_PORT: String(LIVEKIT_PORT),
  PW_LIVEKIT_READY_PORT: String(LIVEKIT_READY_PORT),
}

const backendServerEnv: Record<string, string> = {
  LSA_CORS_ORIGINS: '["http://127.0.0.1:3100"]',
  LSA_SESSION_DATA_DIR: 'data/playwright-sessions',
  LSA_ENABLE_LIVEKIT: 'true',
  LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER: 'true',
  LSA_LIVEKIT_URL: LIVEKIT_URL,
  LSA_LIVEKIT_API_KEY: 'devkey',
  LSA_LIVEKIT_API_SECRET: 'secret',
}

const frontendServerEnv: Record<string, string> = {
  NEXT_PUBLIC_API_URL: BACKEND_URL,
  NEXT_PUBLIC_WS_URL: `ws://127.0.0.1:${BACKEND_PORT}`,
  NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI: 'true',
  NEXT_PUBLIC_LIVEKIT_URL: LIVEKIT_URL,
  NEXT_PUBLIC_MEDIA_PROVIDER_OVERRIDE: MEDIA_PROVIDER,
  NEXT_TELEMETRY_DISABLED: '1',
  // Disable adaptive stream/dynacast in CI so headless Chrome's small
  // viewport doesn't cause LiveKit to subscribe at a very low layer.
  ...(MEDIA_PROVIDER === 'livekit'
    ? {
        NEXT_PUBLIC_LIVEKIT_ADAPTIVE_STREAM: 'false',
        NEXT_PUBLIC_LIVEKIT_DYNACAST: 'false',
      }
    : {}),
}

const webServers = [
  // LiveKit server is always required (LiveKit is the default transport)
  {
    command: 'node ../scripts/start-livekit-for-playwright.mjs',
    url: `http://127.0.0.1:${LIVEKIT_READY_PORT}`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: livekitServerEnv,
  },
  {
    command:
      'cd ../backend && uv run --python 3.11 --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8100',
    url: `${BACKEND_URL}/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: backendServerEnv,
  },
  {
    command: 'npm run build && npm run start -- --hostname 127.0.0.1 --port 3100',
    url: FRONTEND_URL,
    reuseExistingServer: false,
    timeout: 240_000,
    env: frontendServerEnv,
  },
]

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
  webServer: webServers,
})
