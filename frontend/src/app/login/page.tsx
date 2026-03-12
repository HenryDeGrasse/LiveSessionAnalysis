'use client'

import Image from 'next/image'
import { signIn } from 'next-auth/react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { API_URL } from '@/lib/constants'

const PANEL_CLASSES =
  'rounded-[28px] border border-white/10 bg-white/5 shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur'
const INPUT_CLASSES =
  'w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400'

/**
 * Returns the callbackUrl to redirect to after sign-in. Defaults to '/'.
 */
function useCallbackUrl(): string {
  const searchParams = useSearchParams()
  return searchParams.get('callbackUrl') ?? '/'
}

function LoginForm() {
  const router = useRouter()
  const callbackUrl = useCallbackUrl()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleEmailLogin = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!email.trim() || !password) return

    setSubmitting(true)
    setError('')

    try {
      const result = await signIn('credentials', {
        email: email.trim(),
        password,
        redirect: false,
      })

      if (result?.error) {
        setError('Invalid email or password. Please try again.')
      } else if (result?.ok) {
        router.push(callbackUrl)
        router.refresh()
      } else {
        setError('Sign-in failed. Please try again.')
      }
    } catch {
      setError('An unexpected error occurred. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleGoogleLogin = () => {
    void signIn('google', { callbackUrl })
  }

  const handleGuestLogin = async () => {
    setSubmitting(true)
    setError('')

    try {
      // Create a guest account on the backend.
      const res = await fetch(`${API_URL}/api/auth/guest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      if (!res.ok) {
        throw new Error('Failed to create guest account')
      }

      const data = (await res.json()) as {
        access_token: string
        user: { id: string; name: string; email: string; role: string }
      }

      // Sign in using the credentials provider's token path.
      // The pre-issued backend JWT is passed directly so NextAuth calls
      // GET /api/auth/me to validate it — no password lookup needed.
      const result = await signIn('credentials', {
        token: data.access_token,
        redirect: false,
      })

      if (result?.ok) {
        router.push(callbackUrl)
        router.refresh()
      } else {
        setError('Guest sign-in failed. Please try again.')
      }
    } catch {
      setError('Could not start guest session. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center">
          <div className="mx-auto mb-3 inline-flex items-center gap-2 rounded-full border border-[#0066FF]/30 bg-[#0066FF]/10 px-3 py-1.5">
            <Image
              src="/nerdy-logo.svg"
              alt="Nerdy"
              width={72}
              height={18}
              className="h-[18px] w-auto"
              priority
            />
            <span className="text-xs text-slate-500">·</span>
            <span className="text-xs uppercase tracking-[0.18em] text-slate-400">Live Session Analysis</span>
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">
            Sign in
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Access your tutoring session history and analytics.
          </p>
        </div>

        <section className={`${PANEL_CLASSES} p-8 space-y-5`}>
          {/* Google sign-in */}
          <button
            data-testid="google-signin-button"
            type="button"
            onClick={handleGoogleLogin}
            disabled={submitting}
            className="flex w-full items-center justify-center gap-3 rounded-2xl border border-white/15 bg-white/5 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {/* Google icon (SVG) */}
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
              <path
                fill="#EA4335"
                d="M24 9.5c3.5 0 6.6 1.2 9.1 3.2l6.8-6.8C35.8 2.1 30.2 0 24 0 14.7 0 6.7 5.4 2.8 13.3l7.9 6.1C12.5 13.3 17.8 9.5 24 9.5z"
              />
              <path
                fill="#4285F4"
                d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 6.9-10.1 6.9-17.1z"
              />
              <path
                fill="#FBBC05"
                d="M10.7 28.6A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.6L2.4 13.3A24 24 0 0 0 0 24c0 3.9.9 7.6 2.5 10.9l8.2-6.3z"
              />
              <path
                fill="#34A853"
                d="M24 48c6.2 0 11.5-2.1 15.4-5.6l-7.6-5.9c-2.1 1.4-4.8 2.2-7.8 2.2-6.2 0-11.5-3.8-13.4-9.1l-8.2 6.3C6.8 42.6 14.8 48 24 48z"
              />
            </svg>
            Continue with Google
          </button>

          {/* Divider */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-white/10" />
            </div>
            <div className="relative flex justify-center text-xs uppercase tracking-[0.18em] text-slate-500">
              <span className="bg-transparent px-3">or continue with email</span>
            </div>
          </div>

          {/* Email/password form */}
          <form
            data-testid="email-login-form"
            onSubmit={(e) => void handleEmailLogin(e)}
            className="space-y-4"
          >
            <div>
              <label
                htmlFor="email"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Email
              </label>
              <input
                id="email"
                data-testid="email-input"
                type="email"
                autoComplete="email"
                required
                placeholder="tutor@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={INPUT_CLASSES}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Password
              </label>
              <input
                id="password"
                data-testid="password-input"
                type="password"
                autoComplete="current-password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={INPUT_CLASSES}
              />
            </div>

            {error ? (
              <p
                data-testid="login-error"
                className="rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
              >
                {error}
              </p>
            ) : null}

            <button
              data-testid="email-signin-button"
              type="submit"
              disabled={submitting || !email.trim() || !password}
              className="w-full rounded-2xl bg-[#0066FF] px-4 py-3 text-sm font-medium text-white transition hover:bg-[#3385FF] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {/* Guest access */}
          <div className="border-t border-white/10 pt-4">
            <button
              data-testid="guest-signin-button"
              type="button"
              onClick={() => void handleGuestLogin()}
              disabled={submitting}
              className="w-full rounded-2xl border border-white/10 bg-transparent px-4 py-3 text-sm font-medium text-slate-300 transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Continue as guest
            </button>
            <p className="mt-2 text-center text-xs text-slate-500">
              Guest sessions have limited history. You can upgrade to a full account later.
            </p>
          </div>
        </section>

        {/* Link to register */}
        <p className="text-center text-sm text-slate-400">
          Don&apos;t have an account?{' '}
          <Link
            href="/register"
            className="font-medium text-[#0066FF] transition hover:text-[#3385FF]"
          >
            Create one
          </Link>
        </p>

        <p className="text-center text-xs text-slate-600">
          A Varsity Tutors Platform
        </p>
      </div>
    </main>
  )
}

/**
 * Login page — wrapped in Suspense because useSearchParams() requires it in
 * Next.js App Router when used inside a client component.
 */
export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  )
}
