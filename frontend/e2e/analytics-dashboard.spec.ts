import { expect, test } from '@playwright/test'
import { resetAnalyticsStore, seedSessionSummaries } from './helpers/analytics'
import {
  closeParticipant,
  consentToMedia,
  createSessionFromHome,
  grantMediaPermissions,
  openParticipant,
  waitForAnalyticsSummary,
  waitForConnectedCall,
} from './helpers/session'

test.describe('analytics redesign', () => {
  test.beforeEach(async () => {
    await resetAnalyticsStore()
  })

  test('renders the redesigned analytics dashboard with filters, queue, and drill-down detail', async ({
    page,
  }) => {
    await seedSessionSummaries([
      {
        session_id: 'ada-practice-1',
        tutor_id: 'Coach Ada',
        session_type: 'practice',
        start_time: '2026-03-01T15:00:00.000Z',
        duration_seconds: 2100,
        talk_time_ratio: { tutor: 0.52, student: 0.48 },
        avg_eye_contact: { tutor: 0.74, student: 0.68 },
        avg_energy: { tutor: 0.7, student: 0.63 },
        total_interruptions: 2,
        engagement_score: 84,
        nudges_sent: 1,
      },
      {
        session_id: 'ada-lecture-2',
        tutor_id: 'Coach Ada',
        session_type: 'lecture',
        start_time: '2026-03-03T15:00:00.000Z',
        duration_seconds: 2400,
        talk_time_ratio: { tutor: 0.83, student: 0.17 },
        avg_eye_contact: { tutor: 0.69, student: 0.25 },
        avg_energy: { tutor: 0.64, student: 0.31 },
        total_interruptions: 5,
        engagement_score: 62,
        nudges_sent: 3,
        flagged_moments: [
          {
            timestamp: 180,
            metric_name: 'engagement',
            value: 34,
            direction: 'below',
            description: 'Engagement dropped to 34',
          },
        ],
      },
      {
        session_id: 'ada-discussion-3',
        tutor_id: 'Coach Ada',
        session_type: 'discussion',
        start_time: '2026-03-05T15:00:00.000Z',
        duration_seconds: 2280,
        talk_time_ratio: { tutor: 0.57, student: 0.43 },
        avg_eye_contact: { tutor: 0.72, student: 0.58 },
        avg_energy: { tutor: 0.69, student: 0.49 },
        total_interruptions: 3,
        engagement_score: 76,
        nudges_sent: 1,
      },
      {
        session_id: 'noah-general-1',
        tutor_id: 'Coach Noah',
        session_type: 'general',
        start_time: '2026-03-06T15:00:00.000Z',
        duration_seconds: 1950,
        talk_time_ratio: { tutor: 0.79, student: 0.21 },
        avg_eye_contact: { tutor: 0.67, student: 0.24 },
        avg_energy: { tutor: 0.61, student: 0.22 },
        total_interruptions: 7,
        engagement_score: 48,
        nudges_sent: 3,
        flagged_moments: [
          {
            timestamp: 95,
            metric_name: 'student_talk_time',
            value: 0.02,
            direction: 'below',
            description: 'Student talk time dropped below 5%',
          },
          {
            timestamp: 410,
            metric_name: 'interruptions',
            value: 7,
            direction: 'above',
            description: 'Interruption count reached 7',
          },
        ],
      },
    ])

    await page.goto('/analytics')

    await expect(page.getByTestId('analytics-dashboard')).toBeVisible()
    await expect(page.getByTestId('analytics-stat-total-sessions')).toContainText('4')
    await expect(page.getByTestId('analytics-action-queue')).toContainText(
      'Escalate for coach review'
    )

    await page.getByTestId('analytics-tutor-filter').selectOption('Coach Ada')
    await page.getByTestId('analytics-session-type-filter').selectOption('lecture')

    await expect(page.getByTestId('analytics-scope-label')).toContainText('Coach Ada')
    await expect(page.getByTestId('analytics-scope-label')).toContainText(
      'Lecture / explanation'
    )
    await expect(
      page.getByTestId('analytics-session-card-ada-lecture-2')
    ).toBeVisible()
    await expect(
      page.getByTestId('analytics-session-card-ada-practice-1')
    ).toHaveCount(0)

    await page.getByTestId('analytics-focus-interruptions').click()
    await expect(page.getByTestId('analytics-trend-chart')).toBeVisible()

    await page.getByTestId('analytics-session-card-ada-lecture-2').click()
    await expect(page.getByTestId('analytics-detail-page')).toBeVisible()
    await expect(page.getByTestId('analytics-detail-title')).toContainText(
      'Coach Ada'
    )
    await expect(page.getByTestId('analytics-detail-recommendations')).toContainText(
      'Student eye contact was low'
    )
    await expect(page.getByTestId('analytics-detail-comparison-panel')).toContainText(
      'Based on 2 other stored sessions'
    )
    await expect(page.getByTestId('analytics-detail-flagged-moments')).toContainText(
      'Engagement dropped to 34'
    )

    await page.getByTestId('analytics-detail-series-tutorTalk').click()
    await expect(page.getByTestId('analytics-detail-chart')).toBeVisible()
  })

  test('preserves UI-selected metadata into the redesigned analytics experience after a real session', async ({
    browser,
    page,
    request,
  }) => {
    await grantMediaPermissions(page.context())

    const session = await createSessionFromHome(page, {
      tutorName: 'Coach Mia',
      sessionType: 'practice',
    })

    const student = await openParticipant(browser, session.studentUrl)

    try {
      await consentToMedia(page)
      await consentToMedia(student.page)

      await waitForConnectedCall(page)
      await waitForConnectedCall(student.page)

      page.on('dialog', (dialog) => dialog.accept())
      await page.getByTestId('end-session-button').click()

      await waitForAnalyticsSummary(request, session.sessionId)

      await page.goto('/analytics')
      await expect(
        page.getByTestId(`analytics-session-card-${session.sessionId}`)
      ).toContainText('Coach Mia')
      await expect(
        page.getByTestId(`analytics-session-card-${session.sessionId}`)
      ).toContainText('Practice / problem solving')

      await page.getByTestId(`analytics-session-card-${session.sessionId}`).click()
      await expect(page.getByTestId('analytics-detail-metadata')).toContainText(
        'Coach Mia'
      )
      await expect(page.getByTestId('analytics-detail-metadata')).toContainText(
        'Practice / problem solving'
      )
    } finally {
      await closeParticipant(student)
    }
  })
})
