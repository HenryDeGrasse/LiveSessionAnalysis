/**
 * AuthGuard component tests.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthGuard } from './AuthGuard'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => '/dashboard',
}))

let mockSessionStatus: 'loading' | 'authenticated' | 'unauthenticated' =
  'loading'
let mockSessionData: { user: { name: string } } | null = null

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: mockSessionData,
    status: mockSessionStatus,
  }),
}))

beforeEach(() => {
  mockPush.mockClear()
  mockSessionStatus = 'loading'
  mockSessionData = null
})

afterEach(() => {
  cleanup()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('AuthGuard', () => {
  it('shows loading spinner while session is loading', () => {
    mockSessionStatus = 'loading'
    render(
      <AuthGuard>
        <div data-testid="protected-content">Content</div>
      </AuthGuard>
    )
    expect(screen.getByTestId('auth-guard-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
  })

  it('redirects to /login when unauthenticated', () => {
    mockSessionStatus = 'unauthenticated'
    mockSessionData = null
    render(
      <AuthGuard>
        <div data-testid="protected-content">Content</div>
      </AuthGuard>
    )
    expect(mockPush).toHaveBeenCalledWith(
      '/login?callbackUrl=%2Fdashboard'
    )
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
  })

  it('renders children when authenticated', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice' } }
    render(
      <AuthGuard>
        <div data-testid="protected-content">Content</div>
      </AuthGuard>
    )
    expect(screen.getByTestId('protected-content')).toBeInTheDocument()
  })
})
