import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from '@playwright/test'

const FRONTEND_ORIGIN = 'http://127.0.0.1:3100'
const BACKEND_ORIGIN = 'http://127.0.0.1:8100'

export interface SessionUrls {
  sessionId: string
  tutorUrl: string
  studentUrl: string
}

export interface ParticipantHandle {
  context: BrowserContext
  page: Page
}

async function ensureDebugPanel(page: Page) {
  if (await page.getByTestId('coach-debug-panel').isVisible().catch(() => false)) {
    return
  }

  const debugToggle = page.getByTestId('coach-debug-toggle')
  if (await debugToggle.isVisible().catch(() => false)) {
    await debugToggle.click()
  }

  await expect(page.getByTestId('coach-debug-panel')).toBeVisible()
}

export async function grantMediaPermissions(context: BrowserContext) {
  await context.grantPermissions(['camera', 'microphone'], {
    origin: FRONTEND_ORIGIN,
  })
}

export async function createSession(
  request: APIRequestContext,
  sessionType = 'practice'
): Promise<SessionUrls> {
  const response = await request.post(`${BACKEND_ORIGIN}/api/sessions`, {
    data: {
      tutor_id: 'playwright-tutor',
      session_type: sessionType,
    },
  })
  expect(response.ok()).toBeTruthy()

  const body = (await response.json()) as {
    session_id: string
    tutor_token: string
    student_token: string
  }

  return {
    sessionId: body.session_id,
    tutorUrl: `${FRONTEND_ORIGIN}/session/${body.session_id}?token=${body.tutor_token}&debug=1`,
    studentUrl: `${FRONTEND_ORIGIN}/session/${body.session_id}?token=${body.student_token}&debug=1`,
  }
}

export async function createSessionFromHome(
  page: Page,
  options: {
    tutorName: string
    sessionType: 'general' | 'lecture' | 'practice' | 'discussion'
  }
): Promise<SessionUrls> {
  await page.goto('/')
  await page.getByTestId('tutor-name-input').fill(options.tutorName)
  await page.getByTestId('session-type-select').selectOption(options.sessionType)
  await page.getByTestId('create-session-button').click()

  await expect(page.getByTestId('session-created-card')).toBeVisible()

  const sessionText =
    (await page.getByTestId('created-session-id').textContent()) || ''
  const sessionId = sessionText.replace('Session ID:', '').trim()
  const studentUrl =
    (await page.getByTestId('student-join-link').textContent())?.trim() || ''

  expect(sessionId).not.toBe('')
  expect(studentUrl).toContain(`/session/${sessionId}?token=`)

  await page.getByTestId('join-as-tutor-button').click()
  await page.waitForURL(
    (url) => url.pathname === `/session/${sessionId}` && url.searchParams.has('token')
  )

  const tutorUrl = page.url().includes('debug=1')
    ? page.url()
    : `${page.url()}&debug=1`

  if (!page.url().includes('debug=1')) {
    await page.goto(tutorUrl)
  }

  return {
    sessionId,
    tutorUrl,
    studentUrl: `${studentUrl}&debug=1`,
  }
}

export async function openParticipant(
  browser: Browser,
  url: string
): Promise<ParticipantHandle> {
  const context = await browser.newContext()
  await grantMediaPermissions(context)

  const page = await context.newPage()
  await page.goto(url)
  await expect(page.getByTestId('consent-start-button')).toBeVisible()
  return { context, page }
}

export async function consentToMedia(page: Page) {
  await page.getByTestId('consent-start-button').click()
  await expect(page.getByTestId('call-surface')).toBeVisible()
}

export async function waitForConnectedCall(page: Page) {
  await ensureDebugPanel(page)
  await expect.poll(async () => {
    return (await page.getByTestId('debug-call-status').textContent()) ?? ''
  }).toContain('Connected')

  await expect.poll(async () => {
    return (await page.getByTestId('debug-remote-tracks').textContent()) ?? ''
  }).not.toContain('Remote tracks: 0')

  await expect.poll(async () => {
    return (await page.getByTestId('debug-remote-video-present').textContent()) ?? ''
  }).toContain('yes')

  await expect.poll(async () => {
    return (await page.getByTestId('debug-remote-audio-present').textContent()) ?? ''
  }).toContain('yes')

  await expect(page.getByTestId('remote-video')).toBeVisible()
  await expect(page.getByTestId('local-video')).toBeVisible()
}

export async function waitForTutorMetrics(page: Page) {
  await ensureDebugPanel(page)
  await expect(page.getByTestId('coach-overlay')).toBeVisible()
  await expect(page.getByTestId('debug-current-metrics')).toBeVisible()
}

export async function expectStudentNoTutorMetrics(page: Page) {
  await ensureDebugPanel(page)
  await expect(page.getByTestId('coach-overlay')).toHaveCount(0)
  await expect(page.getByTestId('debug-no-live-metrics')).toBeVisible()
}

export async function waitForAnalyticsSummary(
  request: APIRequestContext,
  sessionId: string
) {
  await expect
    .poll(
      async () => {
        const response = await request.get(
          `${BACKEND_ORIGIN}/api/analytics/sessions/${sessionId}`
        )
        return response.status()
      },
      {
        timeout: 20_000,
      }
    )
    .toBe(200)
}

export async function closeParticipant(handle: ParticipantHandle) {
  await handle.context.close()
}
