'use client'

import Image from 'next/image'
import { signIn } from 'next-auth/react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { API_URL } from '@/lib/constants'

const PANEL_CLASSES =
  'rounded-[28px] border border-white/10 bg-white/5 shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur'
const INPUT_CLASSES =
  'w-full rounded-2xl border border-white/10 bg-[#1e2545]/80 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-[#7b6ef6]/60'
type Role = 'tutor' | 'student'

function validatePassword(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters.'
  return null
}

export default function RegisterPage() {
  const router = useRouter()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<Role>('tutor')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')
  const redirectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (redirectTimeoutRef.current) {
        clearTimeout(redirectTimeoutRef.current)
      }
    }
  }, [])

  const passwordError = password ? validatePassword(password) : null
  const confirmError =
    confirmPassword && password !== confirmPassword
      ? 'Passwords do not match.'
      : null

  const canSubmit =
    name.trim() &&
    email.trim() &&
    password &&
    !passwordError &&
    !confirmError &&
    !submitting

  const redirectAfterSuccess = (url: string, refresh = true) => {
    setSuccess(true)
    redirectTimeoutRef.current = setTimeout(() => {
      router.push(url)
      if (refresh) {
        router.refresh()
      }
    }, 800)
  }

  const handleRegister = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError('')

    try {
      // Register with the backend.
      const res = await fetch(`${API_URL}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          password,
          role,
        }),
      })

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string }
        throw new Error(body.detail ?? 'Registration failed. Please try again.')
      }

      // Auto sign-in after successful registration.
      const result = await signIn('credentials', {
        email: email.trim(),
        password,
        redirect: false,
      })

      if (result?.ok) {
        redirectAfterSuccess('/')
      } else {
        // Registration succeeded but auto sign-in failed — send to login.
        redirectAfterSuccess('/login', false)
      }
    } catch (registerError) {
      setError(
        registerError instanceof Error
          ? registerError.message
          : 'Registration failed. Please try again.'
      )
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] px-4 py-12">
        <div className="flex flex-col items-center gap-4 text-center">
          {/* Animated checkmark circle */}
          <div className="flex h-16 w-16 animate-scale-in items-center justify-center rounded-full bg-emerald-500/20 ring-2 ring-emerald-400/60">
            <svg
              className="h-8 w-8 text-emerald-400"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </div>
          <p className="text-base font-medium text-white">Account created!</p>
          <p className="text-sm text-slate-400">Signing you in…</p>
        </div>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center">
          <div className="mx-auto mb-3 inline-flex items-center gap-2 rounded-full border border-[#4a5fff]/30 bg-[#4a5fff]/10 px-3 py-1.5">
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
            Create account
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Set up your tutor or student profile to track your sessions.
          </p>
        </div>

        <section className={`${PANEL_CLASSES} p-8`}>
          <form
            data-testid="register-form"
            onSubmit={(e) => void handleRegister(e)}
            className="space-y-5"
          >
            {/* Name */}
            <div>
              <label
                htmlFor="name"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Full name
              </label>
              <input
                id="name"
                data-testid="name-input"
                type="text"
                autoComplete="name"
                required
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={INPUT_CLASSES}
              />
            </div>

            {/* Email */}
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
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={INPUT_CLASSES}
              />
            </div>

            {/* Password */}
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
                autoComplete="new-password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={INPUT_CLASSES}
              />
              {passwordError ? (
                <p className="mt-1 text-xs text-rose-400">{passwordError}</p>
              ) : null}
            </div>

            {/* Confirm password */}
            <div>
              <label
                htmlFor="confirm-password"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Confirm password
              </label>
              <input
                id="confirm-password"
                data-testid="confirm-password-input"
                type="password"
                autoComplete="new-password"
                required
                placeholder="••••••••"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={INPUT_CLASSES}
              />
              {confirmError ? (
                <p className="mt-1 text-xs text-rose-400">{confirmError}</p>
              ) : null}
            </div>

            {/* Role — pill selector */}
            <div>
              <span className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400">
                I am a…
              </span>
              <div className="flex gap-2" role="radiogroup" aria-label="Role">
                {(['tutor', 'student'] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="radio"
                    aria-checked={role === r}
                    data-testid={`role-pill-${r}`}
                    onClick={() => setRole(r)}
                    className={`flex-1 rounded-2xl border px-4 py-3 text-sm font-medium transition ${
                      role === r
                        ? 'border-[#7b6ef6]/50 bg-[#7b6ef6]/20 text-white'
                        : 'border-white/10 bg-[#1e2545]/80 text-slate-400 hover:bg-white/5'
                    }`}
                  >
                    {r.charAt(0).toUpperCase() + r.slice(1)}
                  </button>
                ))}
              </div>
              {/* Hidden native select for form data / test compat */}
              <select
                id="role"
                data-testid="role-select"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="sr-only"
                tabIndex={-1}
                aria-hidden="true"
              >
                <option value="tutor">Tutor</option>
                <option value="student">Student</option>
              </select>
            </div>

            {/* Error message */}
            {error ? (
              <p
                data-testid="register-error"
                className="rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
              >
                {error}
              </p>
            ) : null}

            <button
              data-testid="register-submit-button"
              type="submit"
              disabled={!canSubmit}
              className="w-full rounded-2xl bg-gradient-to-r from-[#7b6ef6] to-[#4a90d9] px-4 py-3 text-sm font-medium text-white transition hover:shadow-[0_4px_24px_rgba(123,110,246,0.35)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        </section>

        {/* Link to login */}
        <p className="text-center text-sm text-slate-400">
          Already have an account?{' '}
          <Link
            href="/login"
            className="font-medium text-[#7b6ef6] transition hover:text-[#9b8df8]"
          >
            Sign in
          </Link>
        </p>

        <p className="text-center text-xs text-slate-600">
          A Varsity Tutors Platform
        </p>
      </div>
    </main>
  )
}
