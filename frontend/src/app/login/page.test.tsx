/**
 * Login page component tests.
 *
 * Tests verify the key UI elements are present:
 *   - Google sign-in button
 *   - Email / password form fields
 *   - Guest sign-in button
 *   - Error display
 *   - Link to register
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './page'

// ---------------------------------------------------------------------------
// NextAuth mocks
// ---------------------------------------------------------------------------
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockSignIn = vi.fn<(...args: any[]) => Promise<{ ok: boolean; error: string | null; status: number; url: string | null; code?: string }>>()

vi.mock('next-auth/react', () => ({
  // The mock is typed loosely so we can return minimal objects in tests.
  signIn: (...args: unknown[]) => mockSignIn(...args),
}))

// ---------------------------------------------------------------------------
// next/navigation mocks
// ---------------------------------------------------------------------------
const mockPush = vi.fn()
const mockRefresh = vi.fn()
const mockSearchParams = { get: vi.fn().mockReturnValue(null) }

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => '/',
}))

// ---------------------------------------------------------------------------
// next/link mock
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
// @/lib/constants mock
// ---------------------------------------------------------------------------
vi.mock('@/lib/constants', () => ({
  API_URL: 'http://localhost:8000',
}))

// ---------------------------------------------------------------------------
// global fetch mock
// ---------------------------------------------------------------------------
const mockFetch = vi.fn<typeof fetch>()

beforeEach(() => {
  mockSignIn.mockClear()
  mockFetch.mockClear()
  mockPush.mockClear()
  mockRefresh.mockClear()
  vi.stubGlobal('fetch', mockFetch)
  vi.useFakeTimers()
  mockSignIn.mockResolvedValue({ ok: true, error: null, status: 200, url: '/' })
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('LoginPage', () => {
  it('renders Google sign-in button', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('google-signin-button')).toBeInTheDocument()
    expect(screen.getByTestId('google-signin-button')).toHaveTextContent(
      'Continue with Google'
    )
  })

  it('renders email and password inputs', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('email-input')).toBeInTheDocument()
    expect(screen.getByTestId('password-input')).toBeInTheDocument()
  })

  it('renders email sign-in submit button', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('email-signin-button')).toBeInTheDocument()
  })

  it('renders guest sign-in button', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('guest-signin-button')).toBeInTheDocument()
    expect(screen.getByTestId('guest-signin-button')).toHaveTextContent(
      'Continue as guest'
    )
  })

  it('renders link to register page', () => {
    render(<LoginPage />)
    const registerLink = screen.getByRole('link', { name: /create one/i })
    expect(registerLink).toBeInTheDocument()
    expect(registerLink).toHaveAttribute('href', '/register')
  })

  it('email sign-in button is disabled when fields are empty', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('email-signin-button')).toBeDisabled()
  })

  it('shows error message when credentials are wrong', async () => {
    mockSignIn.mockResolvedValueOnce({
      ok: false,
      error: 'CredentialsSignin',
      status: 401,
      url: null,
    })

    render(<LoginPage />)

    fireEvent.change(screen.getByTestId('email-input'), {
      target: { value: 'user@test.com' },
    })
    fireEvent.change(screen.getByTestId('password-input'), {
      target: { value: 'wrongpass' },
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('email-signin-button'))
    })

    expect(screen.getByTestId('login-error')).toBeInTheDocument()
  })

  it('navigates to / on successful sign-in', async () => {
    mockSignIn.mockResolvedValueOnce({
      ok: true,
      error: null,
      status: 200,
      url: '/',
    })

    render(<LoginPage />)

    fireEvent.change(screen.getByTestId('email-input'), {
      target: { value: 'user@test.com' },
    })
    fireEvent.change(screen.getByTestId('password-input'), {
      target: { value: 'correctpass' },
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('email-signin-button'))
    })

    // The login page uses a short success-state delay before redirecting.
    await act(async () => {
      vi.runAllTimers()
    })

    expect(mockPush).toHaveBeenCalledWith('/')
  })
})
