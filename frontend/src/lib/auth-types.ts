/**
 * TypeScript augmentations for NextAuth session and JWT types.
 *
 * Import this file anywhere that needs access to the extended session shape,
 * or simply rely on the global augmentations declared here by importing
 * from @/lib/auth (which re-exports these types via auth.ts).
 */
import type { DefaultSession } from 'next-auth'

// Re-export for convenience
export type { DefaultSession }

/**
 * The role a user can have in the system.
 * - 'tutor' : authenticated tutor (email/Google)
 * - 'student': authenticated student
 * - 'guest'  : anonymous guest account
 */
export type UserRole = 'tutor' | 'student' | 'guest'

declare module 'next-auth' {
  /**
   * The shape of the session object exposed to the client via useSession()
   * and server via auth().
   *
   * All auth-specific fields live under session.user so that:
   *   - session.user.id          — backend user ID (UUID string)
   *   - session.user.role        — user role
   *   - session.user.accessToken — backend JWT (attach as Authorization: Bearer)
   *   - session.user.isGuest     — true for anonymous guest accounts
   */
  interface Session {
    user: {
      /** Backend user ID (UUID string). Canonical identity field. */
      id: string
      /** Backend user ID alias — same value as `id`, kept for explicitness. */
      backendUserId?: string
      /** User role in the system. */
      role?: UserRole
      /**
       * Backend-issued JWT.
       * Attach as `Authorization: Bearer <accessToken>` for API calls.
       */
      accessToken?: string
      /**
       * True when this is an anonymous guest account (created via POST /api/auth/guest).
       * Guest users see an upgrade banner and have limited session history retention.
       */
      isGuest?: boolean
    } & DefaultSession['user']
  }

  /**
   * Extended User shape returned by Credentials.authorize() or built from
   * the Google sign-in callback. Fields here are persisted into the JWT.
   */
  interface User {
    /** Backend user ID. */
    backendUserId?: string
    /** User role. */
    role?: UserRole
    /** Backend-issued JWT. */
    accessToken?: string
    /** True when this is an anonymous guest account. */
    isGuest?: boolean
  }
}

/**
 * In Auth.js v5, the JWT interface lives in @auth/core/jwt.
 * next-auth/jwt re-exports it, but module augmentation must target
 * the originating module.
 */
declare module '@auth/core/jwt' {
  /** The JWT stored server-side between requests. */
  interface JWT {
    /** Backend-issued access token. */
    accessToken?: string
    /** User role. */
    role?: UserRole
    /** Backend user ID. */
    backendUserId?: string
    /** True when this is an anonymous guest account. */
    isGuest?: boolean
  }
}
