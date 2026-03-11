'use client'

/**
 * AuthGuard — redirects unauthenticated users to /login.
 *
 * Wrap any page or layout that requires authentication:
 * ```tsx
 * <AuthGuard>
 *   <ProtectedPageContent />
 * </AuthGuard>
 * ```
 *
 * While the session is loading, a minimal dark-mode spinner is shown so there
 * is no layout shift or flash of protected content.
 *
 * The current path is passed as `callbackUrl` so users land back where they
 * were after signing in.
 */
import { useSession } from 'next-auth/react'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'

interface AuthGuardProps {
  children: React.ReactNode
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { data: session, status } = useSession()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (status === 'loading') return

    if (!session) {
      const callbackUrl = encodeURIComponent(pathname)
      router.push(`/login?callbackUrl=${callbackUrl}`)
    }
  }, [session, status, router, pathname])

  // Show loading indicator while the session is being fetched.
  if (status === 'loading') {
    return (
      <div
        data-testid="auth-guard-loading"
        className="flex min-h-screen items-center justify-center bg-slate-950"
      >
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-sky-400" />
      </div>
    )
  }

  // If the user is not authenticated, render nothing while the redirect fires.
  if (!session) {
    return null
  }

  return <>{children}</>
}
