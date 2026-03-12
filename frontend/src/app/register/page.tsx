'use client'

import Image from 'next/image'
import { signIn } from 'next-auth/react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { API_URL } from '@/lib/constants'

const PANEL_CLASSES =
  'rounded-[28px] border border-white/10 bg-white/5 shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur'
const INPUT_CLASSES =
  'w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400'
const SELECT_CLASSES = `${INPUT_CLASSES} appearance-none`

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
  const [error, setError] = useState('')

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
        router.push('/')
        router.refresh()
      } else {
        // Registration succeeded but auto sign-in failed — send to login.
        router.push('/login')
      }
    } catch (registerError) {
      setError(
        registerError instanceof Error
          ? registerError.message
          : 'Registration failed. Please try again.'
      )
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

            {/* Role */}
            <div>
              <label
                htmlFor="role"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                I am a…
              </label>
              <select
                id="role"
                data-testid="role-select"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className={SELECT_CLASSES}
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
              className="w-full rounded-2xl bg-[#0066FF] px-4 py-3 text-sm font-medium text-white transition hover:bg-[#3385FF] disabled:cursor-not-allowed disabled:opacity-60"
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
            className="font-medium text-[#0066FF] transition hover:text-[#3385FF]"
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
