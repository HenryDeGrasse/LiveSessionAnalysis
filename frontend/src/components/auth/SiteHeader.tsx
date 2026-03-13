'use client'

/**
 * SiteHeader — floating glass navigation bar shown on all pages except
 * the home page (`/`) and live-session pages (`/session/*`).
 *
 * Provides:
 *  - Nerdy logo → links to dashboard (/)
 *  - Contextual breadcrumb (e.g. "Analytics" or session title)
 *  - UserMenu on the right
 *
 * The home page renders its own inline UserMenu, so SiteHeader hides there
 * to avoid duplication.  Session pages have their own full-screen controls.
 */
import Image from 'next/image'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { UserMenu } from './UserMenu'

function useBreadcrumbs(): Array<{ label: string; href?: string }> {
  const pathname = usePathname()

  if (pathname === '/analytics') {
    return [{ label: 'Analytics' }]
  }

  if (pathname.startsWith('/analytics/')) {
    return [
      { label: 'Analytics', href: '/analytics' },
      { label: 'Session review' },
    ]
  }

  if (pathname === '/login') return [{ label: 'Sign in' }]
  if (pathname === '/register') return [{ label: 'Create account' }]

  return []
}

export function SiteHeader() {
  const pathname = usePathname()
  const breadcrumbs = useBreadcrumbs()

  // Home page renders UserMenu in its hero section; live session pages have
  // their own top-right controls and should stay visually clean.
  if (pathname === '/' || pathname.startsWith('/session/')) return null

  return (
    <header className="fixed left-0 right-0 top-0 z-50">
      <nav className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3">
        {/* Glass bar */}
        <div className="flex flex-1 items-center gap-3 rounded-full border border-white/10 bg-[#1a1f3a]/80 px-4 py-2 shadow-lg backdrop-blur-md">
          {/* Logo → dashboard */}
          <Link
            href="/"
            className="flex shrink-0 items-center gap-2 rounded-full px-1 py-0.5 transition hover:opacity-80"
            aria-label="Go to dashboard"
          >
            <Image
              src="/nerdy-logo.svg"
              alt="Nerdy"
              width={60}
              height={16}
              className="h-4 w-auto"
              priority
            />
          </Link>

          {/* Breadcrumb */}
          {breadcrumbs.length > 0 && (
            <>
              <span className="h-4 w-px bg-white/15" aria-hidden="true" />
              <div className="flex items-center gap-1.5 text-sm">
                <Link
                  href="/"
                  className="text-slate-500 transition hover:text-slate-300"
                >
                  Dashboard
                </Link>
                {breadcrumbs.map((crumb, i) => (
                  <span key={i} className="flex items-center gap-1.5">
                    <span className="text-slate-600" aria-hidden="true">
                      /
                    </span>
                    {crumb.href ? (
                      <Link
                        href={crumb.href}
                        className="text-slate-400 transition hover:text-slate-200"
                      >
                        {crumb.label}
                      </Link>
                    ) : (
                      <span className="text-slate-300">{crumb.label}</span>
                    )}
                  </span>
                ))}
              </div>
            </>
          )}

          {/* Spacer */}
          <div className="flex-1" />

          {/* User menu */}
          <UserMenu />
        </div>
      </nav>
    </header>
  )
}
