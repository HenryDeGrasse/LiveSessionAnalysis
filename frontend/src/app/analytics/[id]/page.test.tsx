/**
 * Analytics detail page — role-based rendering tests.
 *
 * Verifies that:
 *   - Tutor view shows coaching sections (rubric, recommendations, nudge history).
 *   - Student view hides those coaching-only sections.
 *   - Both views show the flagged moments section.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import SessionDetailPage from './page'
import { apiFetch } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Minimal SessionSummary fixture
// ---------------------------------------------------------------------------
const MOCK_SESSION = {
  session_id: 'session-test-001',
  session_title: 'Algebra review · Jan 1, 10:00 AM',
  tutor_id: 'Alice',
  start_time: '2026-01-01T10:00:00Z',
  end_time: '2026-01-01T10:45:00Z',
  duration_seconds: 2700,
  session_type: 'general',
  media_provider: 'livekit',
  talk_time_ratio: { tutor: 0.6, student: 0.4 },
  avg_eye_contact: { tutor: 0.8, student: 0.7 },
  avg_energy: { tutor: 0.75, student: 0.7 },
  total_interruptions: 2,
  engagement_score: 75,
  flagged_moments: [],
  timeline: {},
  recommendations: ['Try asking more questions'],
  nudges_sent: 1,
  degradation_events: 0,
  nudge_details: [
    {
      nudge_type: 'check_for_understanding',
      message: 'Student has been quiet',
      timestamp: '00:12:00',
      priority: 'medium',
    },
  ],
  turn_counts: { tutor: 10, student: 8 },
}

// ---------------------------------------------------------------------------
// Mock: next/navigation
// ---------------------------------------------------------------------------
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'session-test-001' }),
}))

// ---------------------------------------------------------------------------
// Mock: next-auth/react — configurable role
// ---------------------------------------------------------------------------
let mockUserRole: string | undefined = 'tutor'

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        id: 'user-001',
        role: mockUserRole,
        accessToken: 'test-access-token',
      },
    },
    status: 'authenticated',
  }),
}))

// ---------------------------------------------------------------------------
// Mock: @/lib/api-client
// ---------------------------------------------------------------------------
vi.mock('@/lib/api-client', () => ({
  apiFetch: vi.fn(),
}))
const mockApiFetch = apiFetch as Mock

// ---------------------------------------------------------------------------
// Mock: next/link
// ---------------------------------------------------------------------------
vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string
    children: React.ReactNode
    [key: string]: unknown
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

// ---------------------------------------------------------------------------
// Mock: recharts (avoids jsdom rendering failures)
// ---------------------------------------------------------------------------
vi.mock('recharts', () => ({
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="mock-line-chart">{children}</div>
  ),
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceDot: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}))

// ---------------------------------------------------------------------------
// Mock: @/components/charts
// ---------------------------------------------------------------------------
vi.mock('@/components/charts', () => ({
  DonutChart: () => <div data-testid="mock-donut-chart" />,
  NudgeHistoryItem: ({
    nudge,
  }: {
    nudge: { nudge_type: string; message: string }
  }) => (
    <div data-testid="mock-nudge-item">
      {nudge.nudge_type}: {nudge.message}
    </div>
  ),
}))

// ---------------------------------------------------------------------------
// Mock: @/components/auth/AuthGuard — render children directly
// ---------------------------------------------------------------------------
vi.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------
beforeEach(() => {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.includes('/recommendations')) {
      return Promise.resolve(
        new Response(JSON.stringify(['Try asking more questions']), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    }
    if (path.includes('/student-insights')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            engagement_percent: 75,
            talk_time_percent: 35,
            attention_score: 72,
            tips: ['Great job staying engaged!'],
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      )
    }
    if (path.includes('/sessions?')) {
      // peer sessions for comparison
      return Promise.resolve(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    }
    // default: return the mock session
    return Promise.resolve(
      new Response(JSON.stringify(MOCK_SESSION), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  })
})

afterEach(() => {
  mockUserRole = 'tutor'
  cleanup()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('SessionDetailPage — tutor view', () => {
  it('shows the coaching rubric section for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(screen.getByTestId('analytics-detail-rubric')).toBeInTheDocument()
    })
  })

  it('shows the recommendations section for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-recommendations')
      ).toBeInTheDocument()
    })
  })

  it('shows the nudge history section for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-nudge-history')
      ).toBeInTheDocument()
    })
  })

  it('shows flagged moments for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })
  })

  it('shows the session title for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      const title = screen.getByTestId('analytics-detail-title')
      expect(title).toHaveTextContent('Algebra review')
    })
  })
})

describe('SessionDetailPage — student view', () => {
  it('hides the coaching rubric section for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      // The page should have loaded (flagged moments will be visible)
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId('analytics-detail-rubric')
    ).not.toBeInTheDocument()
  })

  it('hides the recommendations section for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId('analytics-detail-recommendations')
    ).not.toBeInTheDocument()
  })

  it('hides the nudge history section for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId('analytics-detail-nudge-history')
    ).not.toBeInTheDocument()
  })

  it('shows flagged moments for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })
  })

  it('shows the student insights section for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-student-insights')
      ).toBeInTheDocument()
    })

    expect(screen.getByText('Your Session Insights')).toBeInTheDocument()
    expect(
      screen.getByTestId('analytics-student-insights-summary')
    ).toHaveTextContent('Your engagement was 75%')
    expect(
      screen.getByTestId('analytics-student-insights-engagement')
    ).toHaveTextContent('75%')
    expect(
      screen.getByTestId('analytics-student-insights-talk-time')
    ).toHaveTextContent('35%')
    expect(
      screen.getByTestId('analytics-student-insights-attention')
    ).toHaveTextContent('72')
    expect(screen.getByText('Great job staying engaged!')).toBeInTheDocument()
  })

  it('does not show the student insights section for a tutor', async () => {
    mockUserRole = 'tutor'
    render(<SessionDetailPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId('analytics-detail-flagged-moments')
      ).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId('analytics-student-insights')
    ).not.toBeInTheDocument()
  })

  it('shows the session title in the title for a student', async () => {
    mockUserRole = 'student'
    render(<SessionDetailPage />)

    await waitFor(() => {
      const title = screen.getByTestId('analytics-detail-title')
      expect(title).toHaveTextContent('Algebra review')
    })
  })
})
