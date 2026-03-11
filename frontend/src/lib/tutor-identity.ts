/**
 * tutor-identity.ts — localStorage-backed tutor identity helpers.
 *
 * These functions provide a localStorage fallback for tutor name and ID.
 * With NextAuth authentication now in place, prefer reading identity from
 * `useSession()` (client) or `auth()` (server) instead.
 *
 * Migration path:
 *   - Prefer `session.user.name` and `session.user.id` from NextAuth.
 *   - These helpers remain as a graceful fallback for unauthenticated or
 *     guest contexts where no session is available.
 *   - Use the `useTutorIdentity()` React hook which handles the session-first,
 *     localStorage-fallback pattern automatically.
 */

import { useSession } from 'next-auth/react'

const TUTOR_NAME_KEY = 'tutor_name'
const TUTOR_ID_KEY = 'tutor_id'

function getStorage(): Storage | null {
  if (typeof globalThis === 'undefined' || !('localStorage' in globalThis)) {
    return null
  }

  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

function generateTutorId() {
  if (
    typeof globalThis !== 'undefined' &&
    'crypto' in globalThis &&
    typeof globalThis.crypto?.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID().replace(/-/g, '').slice(0, 8)
  }

  return Math.random().toString(36).slice(2, 10)
}

/**
 * Returns the tutor's display name stored in localStorage.
 *
 * @deprecated Prefer `useSession().data?.user?.name` (NextAuth).
 * This localStorage fallback is kept for unauthenticated / guest contexts.
 */
export function getTutorName(): string {
  const storage = getStorage()
  return storage?.getItem(TUTOR_NAME_KEY) || ''
}

/**
 * Persists the tutor's display name in localStorage.
 *
 * @deprecated Prefer updating the user's name via the backend profile endpoint.
 * This localStorage write is kept for unauthenticated / guest contexts.
 */
export function setTutorName(name: string): void {
  const storage = getStorage()
  if (!storage) return
  storage.setItem(TUTOR_NAME_KEY, name)
}

/**
 * Returns a stable anonymous tutor ID stored in localStorage.
 * Generates and persists a new random ID on first call.
 *
 * @deprecated Prefer `useSession().data?.user?.id` (NextAuth backend user ID).
 * This localStorage ID is kept as a fallback for unauthenticated / guest contexts.
 */
export function getTutorId(): string {
  const storage = getStorage()
  const existingId = storage?.getItem(TUTOR_ID_KEY)

  if (existingId) {
    return existingId
  }

  const tutorId = generateTutorId()
  storage?.setItem(TUTOR_ID_KEY, tutorId)
  return tutorId
}

/**
 * React hook that returns the canonical tutor identity.
 *
 * Priority order (graceful migration):
 *   1. NextAuth session: `session.user.name` and `session.user.id` when the
 *      user is authenticated (email, Google, or guest sign-in).
 *   2. localStorage fallback: `getTutorName()` / `getTutorId()` when no
 *      session is available (unauthenticated or session still loading).
 *
 * Usage:
 * ```tsx
 * const { tutorName, tutorId } = useTutorIdentity()
 * ```
 */
export function useTutorIdentity(): { tutorName: string; tutorId: string } {
  const { data: session } = useSession()
  const tutorName = session?.user?.name || getTutorName()
  const tutorId = session?.user?.id || getTutorId()
  return { tutorName, tutorId }
}
