'use client'

/**
 * Client-side provider wrapper.
 *
 * Next.js App Router requires that context providers which use React context
 * (like SessionProvider) be rendered in a Client Component. This thin wrapper
 * lets the root layout (a Server Component) include the SessionProvider.
 */
import { SessionProvider } from 'next-auth/react'

export function Providers({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>
}
