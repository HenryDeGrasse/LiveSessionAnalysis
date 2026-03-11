/**
 * NextAuth (Auth.js v5) configuration.
 *
 * Providers:
 *   - Google OAuth: exchanges the Google id_token with the backend to get a
 *     backend-issued JWT, keeping user storage server-authoritative.
 *   - Credentials: email/password login delegated to backend POST /api/auth/login.
 *
 * Callbacks store the backend access_token and user metadata inside the
 * NextAuth JWT so every session has the accessToken available for API calls.
 */
import NextAuth from 'next-auth'
import Google from 'next-auth/providers/google'
import Credentials from 'next-auth/providers/credentials'
import type { Provider } from 'next-auth/providers'

// Import type augmentations so they are registered globally.
import './auth-types'

/**
 * Backend URL for server-side auth callbacks.
 *
 * Auth callbacks run in the Next.js server process. In docker-compose, the
 * backend service is reachable as http://backend:8000 from the frontend
 * container (server-to-server), but from the browser it is localhost:8000.
 * NEXTAUTH_BACKEND_URL lets you override the backend URL for server-side
 * calls without affecting the public NEXT_PUBLIC_API_URL.
 */
const BACKEND_URL =
  process.env.NEXTAUTH_BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://localhost:8000'

/**
 * Google OAuth is only added as a provider when *both* GOOGLE_CLIENT_ID and
 * GOOGLE_CLIENT_SECRET are set to non-empty values.  The default
 * docker-compose.yml ships those env vars as empty strings, so leaving them
 * blank correctly results in no Google provider being registered — and the
 * `/api/auth/providers` response will not advertise `google`.
 *
 * This avoids exposing a partially-configured OAuth path in local dev.
 */
const googleClientId = process.env.GOOGLE_CLIENT_ID ?? ''
const googleClientSecret = process.env.GOOGLE_CLIENT_SECRET ?? ''
const googleProvider: Provider[] =
  googleClientId && googleClientSecret
    ? [
        Google({
          clientId: googleClientId,
          clientSecret: googleClientSecret,
        }),
      ]
    : []

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    ...googleProvider,

    Credentials({
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
        /**
         * Pre-issued backend JWT — used by the guest sign-in flow.
         * When present, we validate it via GET /api/auth/me instead of
         * calling POST /api/auth/login (which requires a stored password hash).
         */
        token: { label: 'Token', type: 'text' },
      },
      async authorize(credentials) {
        if (!credentials) return null

        // ── Token path: guest or any pre-issued JWT ─────────────────────────
        // When a raw backend token is supplied (e.g. from guest account
        // creation), skip the password-login endpoint entirely and verify the
        // token via GET /api/auth/me.
        if (credentials.token) {
          try {
            const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
              headers: { Authorization: `Bearer ${credentials.token}` },
            })

            if (!res.ok) return null

            const user = (await res.json()) as {
              id: string
              name: string
              email: string | null
              role: string
              is_guest: boolean
            }

            return {
              id: user.id,
              name: user.name,
              email: user.email ?? '',
              backendUserId: user.id,
              role: user.role as 'tutor' | 'student' | 'guest',
              accessToken: credentials.token as string,
              isGuest: user.is_guest,
            }
          } catch {
            return null
          }
        }

        // ── Email/password path ─────────────────────────────────────────────
        if (!credentials.email || !credentials.password) return null

        try {
          const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          })

          if (!res.ok) return null

          const data = (await res.json()) as {
            access_token: string
            user: { id: string; name: string; email: string; role: string; is_guest: boolean }
          }

          return {
            id: data.user.id,
            name: data.user.name,
            email: data.user.email,
            backendUserId: data.user.id,
            role: data.user.role as 'tutor' | 'student' | 'guest',
            accessToken: data.access_token,
            isGuest: data.user.is_guest,
          }
        } catch {
          return null
        }
      },
    }),
  ],

  callbacks: {
    /**
     * jwt callback — persists backend data into the encrypted NextAuth JWT.
     * Called on every sign-in and every time the JWT is read.
     */
    async jwt({ token, user, account }) {
      // Google sign-in: exchange the Google id_token for a backend JWT.
      if (account?.provider === 'google' && account.id_token) {
        // Exchange the Google id_token for a backend-issued JWT.
        // Any failure here throws so NextAuth rejects the sign-in rather than
        // creating a session that has no backend accessToken.
        const res = await fetch(`${BACKEND_URL}/api/auth/google`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ google_token: account.id_token }),
        })

        if (!res.ok) {
          throw new Error(
            `Google backend auth exchange failed with status ${res.status}`
          )
        }

        const data = (await res.json()) as {
          access_token: string
          user: { id: string; name: string; email: string; role: string }
        }
        token.accessToken = data.access_token
        token.backendUserId = data.user.id
        token.role = data.user.role as 'tutor' | 'student' | 'guest'
        token.isGuest = (data.user as { is_guest?: boolean }).is_guest ?? false
        // Update name/email from backend in case they differ from Google.
        token.name = data.user.name
        token.email = data.user.email
      }

      // Credentials sign-in: user already has the backend JWT.
      if (user?.accessToken) {
        token.accessToken = user.accessToken
        token.backendUserId = user.backendUserId
        token.role = user.role
        token.isGuest = user.isGuest ?? false
      }

      return token
    },

    /**
     * session callback — shapes what useSession() / auth() returns to the app.
     *
     * JWT extends Record<string, unknown> so index-accessed properties are
     * typed as `unknown`; explicit casts are required to satisfy the session
     * interface types we declared in auth-types.ts.
     */
    async session({ session, token }) {
      if (session.user) {
        // Expose backend user ID as session.user.id (canonical contract) and
        // also as session.user.backendUserId (explicit alias for clarity).
        const backendId = (token.backendUserId as string | undefined) ?? token.sub ?? undefined
        session.user.id = backendId ?? ''
        session.user.backendUserId = backendId
        session.user.role = token.role as import('./auth-types').UserRole | undefined
        // accessToken lives on session.user so consumers can do
        // session.user.accessToken without reaching into the JWT.
        session.user.accessToken = token.accessToken as string | undefined
        session.user.isGuest = (token.isGuest as boolean | undefined) ?? false
      }
      return session
    },
  },
})
