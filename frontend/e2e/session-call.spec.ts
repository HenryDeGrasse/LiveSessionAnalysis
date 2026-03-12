import { expect, test } from '@playwright/test'
import {
  closeParticipant,
  consentToMedia,
  createSession,
  DEFAULT_MEDIA_PROVIDER,
  expectMediaProvider,
  expectMinimumLocalVideoResolution,
  expectMinimumRemoteVideoResolution,
  expectStudentNoTutorMetrics,
  openParticipant,
  waitForAnalyticsSummary,
  waitForConnectedCall,
  waitForTutorMetrics,
} from './helpers/session'

test.describe(`${DEFAULT_MEDIA_PROVIDER} live tutoring call`, () => {
  test('shows role-specific join copy, lets the student leave cleanly, and preserves tutor/student perspective', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await expect(tutor.page.getByTestId('session-perspective-badge')).toContainText(
        'Tutor workspace'
      )
      await expect(student.page.getByTestId('session-perspective-badge')).toContainText(
        'Student call view'
      )
      await expect(tutor.page.getByTestId('session-perspective-copy')).toContainText(
        'private coaching'
      )
      await expect(student.page.getByTestId('session-perspective-copy')).toContainText(
        'remain private to the tutor'
      )

      await consentToMedia(tutor.page)
      await consentToMedia(student.page)

      await waitForConnectedCall(tutor.page)
      await waitForConnectedCall(student.page)
      await expectMediaProvider(tutor.page)
      await expectMediaProvider(student.page)

      await expect(tutor.page.getByTestId('end-session-button')).toBeVisible()
      await expect(tutor.page.getByTestId('end-session-button')).toHaveAttribute(
        'aria-label',
        'End session for everyone'
      )
      await expect(student.page.getByTestId('leave-session-button')).toBeVisible()
      await expect(student.page.getByTestId('leave-session-button')).toHaveAttribute(
        'aria-label',
        'Leave session'
      )
      await expect(student.page.getByTestId('end-session-button')).toHaveCount(0)

      student.page.on('dialog', (dialog) => dialog.accept())
      await student.page.getByTestId('leave-session-button').click()

      await expect(student.page).toHaveURL('http://127.0.0.1:3100/')
      await expect(student.page.getByTestId('create-session-button')).toBeVisible()
      await expect(tutor.page.getByTestId('participant-disconnected-banner')).toBeVisible()
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  test('connects tutor and student, keeps tutor-only analytics, and finalizes cleanly', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request)
    const tutor = await openParticipant(browser, session.tutorUrl)
    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)

      await waitForConnectedCall(tutor.page)
      await waitForConnectedCall(student.page)

      // Verify video tracks are rendering at a non-trivial resolution.
      // Chrome's fake device in headless mode caps at low resolutions, so we
      // only assert a minimal floor here.  Actual quality (1080p, bitrate,
      // encoding presets) is validated by unit tests on livekit-config and
      // manual testing with real cameras.
      const MIN_W = 160
      const MIN_H = 120
      await expectMinimumLocalVideoResolution(tutor.page, MIN_W, MIN_H)
      await expectMinimumLocalVideoResolution(student.page, MIN_W, MIN_H)
      await expectMinimumRemoteVideoResolution(tutor.page, MIN_W, MIN_H)
      await expectMinimumRemoteVideoResolution(student.page, MIN_W, MIN_H)

      await waitForTutorMetrics(tutor.page)
      await expectStudentNoTutorMetrics(student.page)

      tutor.page.on('dialog', (dialog) => dialog.accept())
      await tutor.page.getByTestId('end-session-button').click()

      await expect(
        tutor.page.getByTestId('session-end-summary-overlay')
      ).toBeVisible()
      await expect(student.page.getByTestId('session-ended-banner')).toBeVisible()
      await expect(tutor.page.getByTestId('view-analytics-button')).toBeVisible()
      await expect(student.page.getByTestId('leave-session-button')).toBeVisible()
      await expect(student.page.getByTestId('leave-session-button')).toHaveAttribute(
        'aria-label',
        'View your session'
      )
      await waitForAnalyticsSummary(request, session.sessionId)

      await tutor.page.getByTestId('view-analytics-button').click()
      await expect(tutor.page).toHaveURL(
        `http://127.0.0.1:3100/analytics/${session.sessionId}`
      )
      await expect(tutor.page.getByTestId('analytics-detail-page')).toBeVisible()

      await student.page.getByTestId('leave-session-button').click()
      await expect(student.page).toHaveURL('http://127.0.0.1:3100/')
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })

  test('recovers after student reconnects within grace period', async ({
    browser,
    request,
  }) => {
    const session = await createSession(request, 'discussion')
    const tutor = await openParticipant(browser, session.tutorUrl)
    let student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(tutor.page)
      await consentToMedia(student.page)

      await waitForConnectedCall(tutor.page)
      await waitForConnectedCall(student.page)

      await closeParticipant(student)
      await expect(tutor.page.getByTestId('participant-disconnected-banner')).toBeVisible()
      await expect
        .poll(async () => {
          return (await tutor.page.getByTestId('debug-call-status').textContent()) ?? ''
        })
        .toContain('Reconnecting')

      student = await openParticipant(browser, session.studentUrl)
      await consentToMedia(student.page)

      await expect(tutor.page.getByTestId('participant-disconnected-banner')).toHaveCount(0)
      await waitForConnectedCall(tutor.page)
      await waitForConnectedCall(student.page)
    } finally {
      await closeParticipant(student)
      await closeParticipant(tutor)
    }
  })
})
