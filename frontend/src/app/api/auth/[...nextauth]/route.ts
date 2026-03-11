/**
 * NextAuth API route handler.
 *
 * Delegates all GET/POST requests to the NextAuth handlers configured in
 * @/lib/auth. This handles the OAuth callback, sign-in, sign-out, and
 * session endpoints under /api/auth/*.
 */
import { handlers } from '@/lib/auth'

export const { GET, POST } = handlers
