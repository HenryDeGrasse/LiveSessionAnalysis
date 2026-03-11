'use client'

/**
 * UserMenu — shows the signed-in user's avatar/name with a sign-out option.
 *
 * Usage in a layout or header:
 * ```tsx
 * <UserMenu />
 * ```
 *
 * - Renders nothing while the session is loading or when the user is signed out.
 * - Shows a guest upgrade banner when role === 'guest'.
 * - Click outside the open dropdown to close it.
 */
import { signOut, useSession } from 'next-auth/react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import type { UserRole } from '@/lib/auth-types'

/**
 * Returns the first letter (uppercased) of the user's name for the avatar
 * fallback, or '?' if no name is available.
 */
function getInitial(name: string | null | undefined): string {
  return name ? name.charAt(0).toUpperCase() : '?'
}

/**
 * Derives a human-readable role label.
 */
function getRoleLabel(role: UserRole | undefined): string {
  if (!role || role === 'guest') return 'Guest'
  return role.charAt(0).toUpperCase() + role.slice(1)
}

export function UserMenu() {
  const { data: session, status } = useSession()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside.
  useEffect(() => {
    if (!open) return

    const handleOutsideClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [open])

  // Don't render anything while loading or when signed out.
  if (status === 'loading' || !session?.user) {
    return null
  }

  const { name, email, role, isGuest: sessionIsGuest } = session.user as {
    name?: string | null
    email?: string | null
    role?: UserRole
    isGuest?: boolean
  }
  // A guest is identified by the explicit is_guest flag from the backend
  // (surfaced as session.user.isGuest).  Role 'guest' is kept as a secondary
  // fallback for any legacy tokens that may not carry the flag.
  const isGuest = sessionIsGuest === true || role === 'guest'

  return (
    <div ref={containerRef} className="relative">
      {/* Avatar button */}
      <button
        data-testid="user-menu-button"
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-label="User menu"
        className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition hover:bg-white/10"
      >
        {/* Initials avatar */}
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sky-500 text-xs font-semibold text-slate-950">
          {getInitial(name)}
        </span>
        <span className="max-w-[120px] truncate">{name ?? 'Guest'}</span>
        {/* Chevron */}
        <svg
          className={`h-3 w-3 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          aria-hidden="true"
        >
          <path d="M2 4l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Dropdown */}
      {open ? (
        <div
          data-testid="user-menu-dropdown"
          className="absolute right-0 z-50 mt-2 w-64 rounded-[20px] border border-white/10 bg-slate-900 p-3 shadow-[0_16px_60px_rgba(2,6,23,0.55)]"
        >
          {/* User info */}
          <div className="mb-3 rounded-2xl bg-white/5 px-4 py-3">
            <p className="text-sm font-medium text-white">{name ?? 'Guest'}</p>
            {email ? (
              <p className="mt-0.5 truncate text-xs text-slate-400">{email}</p>
            ) : null}
            <span className="mt-2 inline-flex rounded-full border border-white/10 bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
              {getRoleLabel(role)}
            </span>
          </div>

          {/* Guest upgrade banner */}
          {isGuest ? (
            <Link
              href="/register"
              onClick={() => setOpen(false)}
              data-testid="guest-upgrade-link"
              className="mb-3 flex items-center justify-between rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs text-amber-100 transition hover:bg-amber-400/15"
            >
              <span>Upgrade to full account to keep your history.</span>
              <span className="ml-2 shrink-0 font-medium text-amber-300">
                Create account →
              </span>
            </Link>
          ) : null}

          {/* Sign out */}
          <button
            data-testid="signout-button"
            type="button"
            onClick={() => {
              setOpen(false)
              void signOut({ callbackUrl: '/login' })
            }}
            className="w-full rounded-2xl border border-white/10 bg-transparent px-4 py-2.5 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white"
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  )
}
