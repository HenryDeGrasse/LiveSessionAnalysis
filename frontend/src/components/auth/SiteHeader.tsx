'use client'

/**
 * SiteHeader — thin fixed-position wrapper that renders the UserMenu in the
 * top-right corner of every page *except* the home page (`/`).
 *
 * The home page renders UserMenu directly inside its hero section, so showing
 * SiteHeader there would produce a duplicate account control. On all other
 * pages (analytics, session, login, register, etc.) SiteHeader provides the
 * only instance of UserMenu.
 *
 * - Rendered null automatically by UserMenu while session is loading or when
 *   the user is signed out, so login/register pages look untouched.
 * - z-50 keeps it above modal/overlay content but below page-level dialogs.
 */
import { usePathname } from 'next/navigation'
import { UserMenu } from './UserMenu'

export function SiteHeader() {
  const pathname = usePathname()

  // Home page renders UserMenu in its hero section; skip here to avoid duplicate.
  if (pathname === '/') return null

  return (
    <div className="fixed right-4 top-4 z-50">
      <UserMenu />
    </div>
  )
}
