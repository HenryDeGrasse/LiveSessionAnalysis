'use client'

/**
 * SiteHeader — thin fixed-position wrapper that renders a Nerdy brand
 * wordmark plus the UserMenu in the top-right corner of every page *except*
 * the home page (`/`) and live-session pages.
 *
 * The home page renders UserMenu directly inside its hero section, so showing
 * SiteHeader there would produce a duplicate account control. On all other
 * pages (analytics, login, register, etc.) SiteHeader provides the brand
 * chip and the only instance of UserMenu.
 *
 * - z-50 keeps it above modal/overlay content but below page-level dialogs.
 */
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { UserMenu } from './UserMenu'

export function SiteHeader() {
  const pathname = usePathname()

  // Home page renders UserMenu in its hero section; live session pages have
  // their own top-right controls and should stay visually clean.
  if (pathname === '/' || pathname.startsWith('/session/')) return null

  return (
    <div className="fixed right-4 top-4 z-50 flex items-center gap-3 rounded-full border border-white/10 bg-slate-950/80 px-3 py-1.5 shadow-lg backdrop-blur">
      <div className="flex items-center gap-2 rounded-full bg-white/5 px-2.5 py-1">
        <Image
          src="/nerdy-logo.svg"
          alt="Nerdy"
          width={60}
          height={16}
          className="h-4 w-auto"
          priority
        />
        <span className="hidden text-[10px] uppercase tracking-[0.18em] text-slate-400 sm:inline">
          Varsity Tutors
        </span>
      </div>
      <span className="h-4 w-px bg-white/15" aria-hidden="true" />
      <UserMenu />
    </div>
  )
}
