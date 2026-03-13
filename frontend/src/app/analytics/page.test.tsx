import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import AnalyticsPage from './page'
import { apiFetch } from '@/lib/api-client'

const MOCK_SESSION = {
  session_id: 'session-test-001',
  session_title: 'Algebra review',
  tutor_id: 'tutor-001',
  student_user_id: 'student-001',
  start_time: '2026-01-01T10:00:00Z',
  end_time: '2026-01-01T10:45:00Z',
  duration_seconds: 2700,
  session_type: 'general',
  media_provider: 'livekit',
  talk_time_ratio: { tutor: 0.6, student: 0.4 },
  avg_eye_contact: { tutor: 0.8, student: 0.7 },
  avg_energy: { tutor: 0.7, student: 0.7 },
  total_interruptions: 2,
  engagement_score: 81,
  flagged_moments: [],
  timeline: {},
  recommendations: [],
  nudges_sent: 1,
  degradation_events: 0,
  turn_counts: { tutor: 8, student: 7 },
}

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        id: 'tutor-001',
        role: 'tutor',
        accessToken: 'test-access-token',
      },
    },
    status: 'authenticated',
  }),
}))

vi.mock('@/lib/api-client', () => ({
  apiFetch: vi.fn(),
}))
const mockApiFetch = apiFetch as Mock

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

vi.mock('recharts', () => ({
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="mock-line-chart">{children}</div>
  ),
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}))

vi.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

describe('AnalyticsPage deletion flow', () => {
  beforeEach(() => {
    mockApiFetch.mockImplementation((path: string, options?: RequestInit & { accessToken?: string }) => {
      if (path === '/api/analytics/sessions' && !options?.method) {
        return Promise.resolve(
          new Response(JSON.stringify([MOCK_SESSION]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }

      if (path === `/api/analytics/sessions/${MOCK_SESSION.session_id}` && options?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }

      return Promise.reject(new Error(`Unhandled request: ${path}`))
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('deletes a session after confirmation', async () => {
    render(<AnalyticsPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId(`analytics-session-card-${MOCK_SESSION.session_id}`)
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId(`analytics-delete-${MOCK_SESSION.session_id}`))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('delete-confirm-button'))

    await waitFor(() => {
      expect(
        screen.queryByTestId(`analytics-session-card-${MOCK_SESSION.session_id}`)
      ).not.toBeInTheDocument()
    })

    expect(mockApiFetch).toHaveBeenCalledWith(
      `/api/analytics/sessions/${MOCK_SESSION.session_id}`,
      expect.objectContaining({
        method: 'DELETE',
        accessToken: 'test-access-token',
      })
    )
  })

  it('shows an inline error when deletion fails', async () => {
    mockApiFetch.mockImplementation((path: string, options?: RequestInit & { accessToken?: string }) => {
      if (path === '/api/analytics/sessions' && !options?.method) {
        return Promise.resolve(
          new Response(JSON.stringify([MOCK_SESSION]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }

      if (path === `/api/analytics/sessions/${MOCK_SESSION.session_id}` && options?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 500 }))
      }

      return Promise.reject(new Error(`Unhandled request: ${path}`))
    })

    render(<AnalyticsPage />)

    await waitFor(() => {
      expect(
        screen.getByTestId(`analytics-session-card-${MOCK_SESSION.session_id}`)
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId(`analytics-delete-${MOCK_SESSION.session_id}`))
    fireEvent.click(screen.getByTestId('delete-confirm-button'))

    await waitFor(() => {
      expect(
        screen.getByText('Failed to delete session. Please try again.')
      ).toBeInTheDocument()
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(
      screen.getByTestId(`analytics-session-card-${MOCK_SESSION.session_id}`)
    ).toBeInTheDocument()
  })
})
