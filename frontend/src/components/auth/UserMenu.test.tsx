/**
 * UserMenu component tests.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { UserMenu } from './UserMenu'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
const mockSignOut = vi.fn()

let mockSessionStatus: 'loading' | 'authenticated' | 'unauthenticated' =
  'loading'
let mockSessionData: {
  user: { name?: string; email?: string; role?: string }
} | null = null

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: mockSessionData,
    status: mockSessionStatus,
  }),
  signOut: (...args: unknown[]) => mockSignOut(...args),
}))

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

beforeEach(() => {
  mockSignOut.mockClear()
  mockSessionStatus = 'loading'
  mockSessionData = null
})

afterEach(() => {
  cleanup()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('UserMenu', () => {
  it('renders nothing while loading', () => {
    mockSessionStatus = 'loading'
    const { container } = render(<UserMenu />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when signed out', () => {
    mockSessionStatus = 'unauthenticated'
    mockSessionData = null
    const { container } = render(<UserMenu />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders avatar button when authenticated', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice', email: 'alice@example.com', role: 'tutor' } }
    render(<UserMenu />)
    expect(screen.getByTestId('user-menu-button')).toBeInTheDocument()
    expect(screen.getByTestId('user-menu-button')).toHaveTextContent('Alice')
  })

  it('opens dropdown on button click', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice', email: 'alice@example.com', role: 'tutor' } }
    render(<UserMenu />)

    expect(screen.queryByTestId('user-menu-dropdown')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('user-menu-button'))
    expect(screen.getByTestId('user-menu-dropdown')).toBeInTheDocument()
  })

  it('shows sign-out button in dropdown', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice', email: 'alice@example.com', role: 'tutor' } }
    render(<UserMenu />)

    fireEvent.click(screen.getByTestId('user-menu-button'))
    expect(screen.getByTestId('signout-button')).toBeInTheDocument()
  })

  it('calls signOut when sign-out button is clicked', async () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice', email: 'alice@example.com', role: 'tutor' } }
    render(<UserMenu />)

    fireEvent.click(screen.getByTestId('user-menu-button'))
    await act(async () => {
      fireEvent.click(screen.getByTestId('signout-button'))
    })
    expect(mockSignOut).toHaveBeenCalledWith({ callbackUrl: '/login' })
  })

  it('shows guest upgrade link for guest users', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Guest 123', email: 'guest_abc@guest.local', role: 'guest' } }
    render(<UserMenu />)

    fireEvent.click(screen.getByTestId('user-menu-button'))
    expect(screen.getByTestId('guest-upgrade-link')).toBeInTheDocument()
  })

  it('does not show guest upgrade link for tutor users', () => {
    mockSessionStatus = 'authenticated'
    mockSessionData = { user: { name: 'Alice', email: 'alice@example.com', role: 'tutor' } }
    render(<UserMenu />)

    fireEvent.click(screen.getByTestId('user-menu-button'))
    expect(screen.queryByTestId('guest-upgrade-link')).not.toBeInTheDocument()
  })
})
