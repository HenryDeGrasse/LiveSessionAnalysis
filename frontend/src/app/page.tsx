'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { AuthGuard } from '@/components/auth/AuthGuard'
import { UserMenu } from '@/components/auth/UserMenu'
import { apiFetch } from '@/lib/api-client'
import type { SessionSummary } from '@/lib/types'
import {
  deriveTrendSnapshot,
  formatMinutes,
  formatScore,
  getSessionHealth,
  getSessionTypeLabel,
  getTrendLabel,
  getTrendTone,
} from '@/lib/analytics'
import { toast } from 'sonner'
import {
  clearActiveSession as clearStoredActiveSession,
  getActiveSession,
  type ActiveSession,
  saveActiveSession,
} from '@/lib/active-session'

/* ─── Types ─────────────────────────────────────────────────────── */

type SessionCreateResponse = {
  session_id: string
  session_title?: string
  tutor_token: string
  student_token: string
  student_tokens?: string[]
  max_students?: number
  media_provider?: 'custom_webrtc' | 'livekit'
  livekit_room_name?: string | null
  coaching_intensity?: string
}

type AnalyticsTone = 'emerald' | 'amber' | 'rose' | 'slate' | 'violet'

/* ─── Constants & option maps ───────────────────────────────────── */

const SESSION_TYPES = [
  { value: 'general', label: 'General' },
  { value: 'lecture', label: 'Lecture' },
  { value: 'practice', label: 'Practice' },
  { value: 'discussion', label: 'Discussion' },
]

const COACHING_INTENSITIES = [
  { value: 'off', label: 'Off' },
  { value: 'subtle', label: 'Subtle' },
  { value: 'normal', label: 'Normal' },
  { value: 'aggressive', label: 'Active' },
]

const VISIBLE_SESSION_COUNT = 4

/* ─── Shared style tokens ───────────────────────────────────────── */

const INPUT_CLASSES =
  'w-full rounded-2xl border border-white/10 bg-[#1e2545]/80 px-4 py-3 text-sm text-white outline-none transition placeholder:text-[#6b7ba0] focus:border-[#7b6ef6]/60 focus:ring-1 focus:ring-[#7b6ef6]/30'

/* ─── Utility helpers ───────────────────────────────────────────── */

function toneClasses(tone: AnalyticsTone) {
  const styles: Record<AnalyticsTone, string> = {
    emerald: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
    amber: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
    rose: 'border-rose-400/30 bg-rose-400/10 text-rose-100',
    slate: 'border-white/8 bg-white/[0.04] text-slate-200',
    violet: 'border-violet-400/30 bg-violet-400/10 text-violet-100',
  }
  return styles[tone]
}

function truncateSessionId(sessionId: string) {
  if (sessionId.length <= 18) return sessionId
  return `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}`
}

function formatBannerTimestamp(timestamp: string) {
  return new Date(timestamp).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function buildSessionHref(sessionId: string, token: string) {
  return `/session/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`
}

async function writeToClipboard(text: string) {
  if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
  await navigator.clipboard.writeText(text)
}

/* ─── Pill selector component ───────────────────────────────────── */

function PillSelector<T extends string>({
  label,
  options,
  value,
  onChange,
  testId,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  testId?: string
}) {
  return (
    <div>
      <p className="mb-2 text-xs uppercase tracking-[0.18em] text-[#8896b3]">{label}</p>
      <div className="flex flex-wrap gap-2" data-testid={testId}>
        {options.map((opt) => {
          const active = opt.value === value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-all ${
                active
                  ? 'bg-gradient-to-r from-[#7b6ef6] to-[#4a90d9] text-white shadow-[0_0_16px_rgba(123,110,246,0.35)]'
                  : 'border border-white/10 bg-white/[0.04] text-[#8896b3] hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              {opt.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ─── Stat card ─────────────────────────────────────────────────── */

function StatCard({
  label,
  value,
  detail,
  tone = 'slate',
}: {
  label: string
  value: string
  detail: string
  tone?: AnalyticsTone
}) {
  const mutedText = tone === 'slate' ? 'text-[#8896b3]' : 'text-white/70'
  const detailText = tone === 'slate' ? 'text-[#6b7ba0]' : 'text-white/80'

  return (
    <div
      className={`rounded-2xl border p-5 ${tone === 'slate' ? 'border-white/8 bg-[#1e2545]/60' : toneClasses(tone)}`}
    >
      <p className={`text-xs uppercase tracking-[0.22em] ${mutedText}`}>{label}</p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className={`mt-2 text-sm ${detailText}`}>{detail}</p>
    </div>
  )
}

/* ─── Session creation card ─────────────────────────────────────── */

function SessionCreationCard({
  sessionType,
  sessionTitle,
  coachingIntensity,
  creating,
  copiedStudentLink,
  error,
  sessionInfo,
  large = false,
  onSessionTypeChange,
  onSessionTitleChange,
  onCoachingIntensityChange,
  onCreate,
  onEnterSession,
  onCopyStudentLink,
}: {
  sessionType: string
  sessionTitle: string
  coachingIntensity: string
  creating: boolean
  copiedStudentLink: boolean
  error: string
  sessionInfo: SessionCreateResponse | null
  large?: boolean
  onSessionTypeChange: (value: string) => void
  onSessionTitleChange: (value: string) => void
  onCoachingIntensityChange: (value: string) => void
  onCreate: () => void
  onEnterSession: () => void
  onCopyStudentLink: () => Promise<void>
}) {
  const panelPadding = large ? 'p-8 md:p-10' : 'p-6'
  const titleClass = large ? 'text-3xl' : 'text-2xl'
  const studentJoinLinks =
    sessionInfo && typeof window !== 'undefined'
      ? (sessionInfo.student_tokens ?? [sessionInfo.student_token]).map(
          (t) =>
            `${window.location.origin}${buildSessionHref(sessionInfo.session_id, t)}`
        )
      : []
  const studentJoinLink = studentJoinLinks[0] ?? ''
  const isMultiStudent = (sessionInfo?.max_students ?? 1) > 1

  return (
    <section
      className={`rounded-2xl border border-white/8 bg-[#1e2545]/60 backdrop-blur ${panelPadding}`}
    >
      <div className="flex flex-col gap-5">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-[#8896b3]">
            Session creation
          </p>
          <h2 className={`mt-2 font-semibold tracking-tight text-white ${titleClass}`}>
            {large ? 'Start your first session' : 'New session'}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#8896b3]">
            Create a live room, share the student link, then review analytics
            afterward.
          </p>
        </div>

        {!sessionInfo ? (
          <div className="space-y-5">
            {/* Session title */}
            <div>
              <label
                htmlFor="session-title"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#8896b3]"
              >
                Session title{' '}
                <span className="normal-case tracking-normal text-[#556080]">
                  (optional)
                </span>
              </label>
              <input
                id="session-title"
                data-testid="session-title-input"
                type="text"
                placeholder="e.g. Algebra review – week 3"
                value={sessionTitle}
                onChange={(e) => onSessionTitleChange(e.target.value)}
                className={INPUT_CLASSES}
              />
            </div>

            {/* Session type pills */}
            <PillSelector
              label="Session type"
              options={SESSION_TYPES}
              value={sessionType}
              onChange={onSessionTypeChange}
              testId="session-type-select"
            />

            {/* Coaching intensity pills */}
            <PillSelector
              label="Coaching intensity"
              options={COACHING_INTENSITIES}
              value={coachingIntensity}
              onChange={onCoachingIntensityChange}
              testId="coaching-intensity-select"
            />

            <input
              type="hidden"
              data-testid="media-provider-select"
              value="livekit"
            />

            <button
              data-testid="create-session-button"
              onClick={onCreate}
              disabled={creating}
              className="w-full rounded-2xl bg-gradient-to-r from-[#7b6ef6] to-[#4a90d9] px-4 py-3 text-sm font-semibold text-white shadow-[0_4px_24px_rgba(123,110,246,0.3)] transition hover:shadow-[0_4px_32px_rgba(123,110,246,0.45)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {creating ? 'Creating session…' : 'Create Session'}
            </button>
          </div>
        ) : (
          /* ── Post-creation: links & enter ── */
          <div data-testid="session-created-card" className="space-y-4">
            <div className="rounded-2xl border border-emerald-400/25 bg-emerald-500/10 p-4">
              <p className="text-sm font-semibold text-emerald-100">
                Session created and ready to enter.
              </p>
              <p
                data-testid="created-session-id"
                className="mt-2 text-xs text-emerald-200/80"
              >
                Ref: {sessionInfo.session_id}
              </p>
              <p className="mt-2 text-sm leading-6 text-emerald-50/85">
                Share the student link below so the student joins the clean call
                view.
              </p>
            </div>

            <div className="rounded-2xl border border-white/8 bg-[#171d3a]/70 p-4">
              {isMultiStudent ? (
                <>
                  <p className="mb-3 text-sm font-medium text-white">
                    Student join links{' '}
                    <span className="text-xs text-[#6b7ba0]">
                      ({sessionInfo?.max_students ?? 1} students)
                    </span>
                  </p>
                  <p className="mb-3 text-xs leading-5 text-[#6b7ba0]">
                    Each student must use a{' '}
                    <strong className="text-[#8896b3]">different</strong> link.
                  </p>
                  <div className="flex flex-col gap-2">
                    {studentJoinLinks.map((link, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-[#8896b3]">
                          Student {i + 1}
                        </span>
                        <code className="min-w-0 flex-1 break-all rounded-xl bg-[#131832] px-3 py-2 text-xs text-[#a0b0d0]">
                          {link}
                        </code>
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              await writeToClipboard(link)
                              toast.success(
                                `Student ${i + 1} link copied!`
                              )
                            } catch {
                              toast.error('Failed to copy link')
                            }
                          }}
                          className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-[#8896b3] transition hover:bg-white/10 hover:text-white"
                        >
                          Copy
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-white">
                      Student join link
                    </p>
                    <button
                      type="button"
                      onClick={() => void onCopyStudentLink()}
                      className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-[#8896b3] transition hover:bg-white/10 hover:text-white"
                    >
                      {copiedStudentLink ? 'Copied ✓' : 'Copy link'}
                    </button>
                  </div>
                  <code
                    data-testid="student-join-link"
                    className="block break-all rounded-xl bg-[#131832] px-3 py-3 text-xs text-[#a0b0d0]"
                  >
                    {studentJoinLink}
                  </code>
                </>
              )}
            </div>

            <button
              data-testid="join-as-tutor-button"
              onClick={onEnterSession}
              className="w-full rounded-2xl bg-white px-4 py-3 text-sm font-semibold text-[#1a1f3a] transition hover:bg-slate-100"
            >
              Enter Session
            </button>
          </div>
        )}

        {error ? <p className="text-sm text-rose-300">{error}</p> : null}
      </div>
    </section>
  )
}

/* ─── Join session card ─────────────────────────────────────────── */

function JoinSessionCard({
  joinSessionId,
  joinToken,
  onJoinSessionIdChange,
  onJoinTokenChange,
  onJoin,
}: {
  joinSessionId: string
  joinToken: string
  onJoinSessionIdChange: (value: string) => void
  onJoinTokenChange: (value: string) => void
  onJoin: () => void
}) {
  return (
    <section className="rounded-2xl border border-white/8 bg-[#1e2545]/60 p-6 backdrop-blur">
      <p className="text-xs uppercase tracking-[0.24em] text-[#8896b3]">
        Universal rejoin
      </p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">
        Join Session
      </h2>
      <p className="mt-2 text-sm leading-6 text-[#6b7ba0]">
        Enter a session ID and token to join as tutor or student.
      </p>

      <div className="mt-5 space-y-4">
        <div>
          <label
            htmlFor="join-session-id"
            className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#8896b3]"
          >
            Session ID
          </label>
          <input
            id="join-session-id"
            type="text"
            placeholder="Session ID"
            value={joinSessionId}
            onChange={(e) => onJoinSessionIdChange(e.target.value)}
            className={INPUT_CLASSES}
          />
        </div>
        <div>
          <label
            htmlFor="join-session-token"
            className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#8896b3]"
          >
            Token
          </label>
          <input
            id="join-session-token"
            type="text"
            placeholder="Join token"
            value={joinToken}
            onChange={(e) => onJoinTokenChange(e.target.value)}
            className={INPUT_CLASSES}
          />
        </div>
        <button
          onClick={onJoin}
          disabled={!joinSessionId.trim() || !joinToken.trim()}
          className="w-full rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-3 text-sm font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Join Session
        </button>
      </div>
    </section>
  )
}

/* ─── Student dashboard ─────────────────────────────────────────── */

function StudentDashboard({
  joinSessionId,
  joinToken,
  onJoinSessionIdChange,
  onJoinTokenChange,
  onJoin,
}: {
  joinSessionId: string
  joinToken: string
  onJoinSessionIdChange: (value: string) => void
  onJoinTokenChange: (value: string) => void
  onJoin: () => void
}) {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <section className="rounded-2xl border border-white/8 bg-[#1e2545]/60 p-6 text-center backdrop-blur md:p-8">
        <p className="text-xs uppercase tracking-[0.24em] text-[#8896b3]">
          Student workspace
        </p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">
          Join a tutoring session
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-[#6b7ba0]">
          Ask your tutor for the session join link, or paste a session ID and
          token below.
        </p>
      </section>

      <JoinSessionCard
        joinSessionId={joinSessionId}
        joinToken={joinToken}
        onJoinSessionIdChange={onJoinSessionIdChange}
        onJoinTokenChange={onJoinTokenChange}
        onJoin={onJoin}
      />
    </div>
  )
}

/* ─── Main page content ─────────────────────────────────────────── */

function HomeContent() {
  const router = useRouter()
  const { data: session } = useSession()

  const userName = session?.user?.name ?? ''
  const userEmail =
    (session?.user as { email?: string } | undefined)?.email ?? ''
  const userRole =
    (session?.user as { role?: string } | undefined)?.role ?? 'tutor'
  const accessToken =
    (session?.user as { accessToken?: string } | undefined)?.accessToken
  const isStudent = userRole === 'student'

  const [sessionType, setSessionType] = useState('general')
  const [sessionTitle, setSessionTitle] = useState('')
  const [coachingIntensity, setCoachingIntensity] = useState('normal')
  const [joinToken, setJoinToken] = useState('')
  const [joinSessionId, setJoinSessionId] = useState('')
  const [creating, setCreating] = useState(false)
  const [copiedStudentLink, setCopiedStudentLink] = useState(false)
  const [error, setError] = useState('')
  const [sessionInfo, setSessionInfo] = useState<SessionCreateResponse | null>(
    null
  )
  const [activeSession, setActiveSession] = useState<ActiveSession | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [sessionsError, setSessionsError] = useState('')
  const [showAllSessions, setShowAllSessions] = useState(false)

  useEffect(() => {
    if (isStudent) {
      clearStoredActiveSession()
      setActiveSession(null)
      return
    }
    const stored = getActiveSession()
    if (!stored) {
      setActiveSession(null)
      return
    }
    // Validate against server — clear if session is ended or gone
    apiFetch(`/api/sessions/${stored.session_id}/info?token=${stored.tutor_token}`, { accessToken })
      .then(async (r) => {
        if (!r.ok) {
          clearStoredActiveSession()
          setActiveSession(null)
          return
        }
        const info = await r.json()
        if (info.ended) {
          clearStoredActiveSession()
          setActiveSession(null)
        } else {
          setActiveSession(stored)
        }
      })
      .catch(() => {
        // Network error — still show the banner (user may be offline)
        setActiveSession(stored)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStudent, accessToken])

  useEffect(() => {
    let cancelled = false
    setSessionsLoading(true)
    setSessionsError('')

    apiFetch('/api/analytics/sessions', { accessToken })
      .then(async (r) => {
        if (!r.ok) throw new Error('Failed to load session history')
        return r.json()
      })
      .then((data) => {
        if (!cancelled) setSessions(Array.isArray(data) ? data : [])
      })
      .catch((err) => {
        if (!cancelled) {
          setSessionsError(
            err instanceof Error ? err.message : 'Failed to load sessions'
          )
          setSessions([])
        }
      })
      .finally(() => {
        if (!cancelled) setSessionsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [accessToken])

  const sortedSessions = useMemo(
    () =>
      [...sessions].sort(
        (a, b) =>
          new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
      ),
    [sessions]
  )

  const visibleSessions = useMemo(
    () =>
      showAllSessions
        ? sortedSessions
        : sortedSessions.slice(0, VISIBLE_SESSION_COUNT),
    [sortedSessions, showAllSessions]
  )

  const recentSessions = useMemo(
    () => sortedSessions.slice(0, 8),
    [sortedSessions]
  )

  const averageEngagement = useMemo(() => {
    if (sortedSessions.length === 0) return 0
    return (
      sortedSessions.reduce((s, x) => s + x.engagement_score, 0) /
      sortedSessions.length
    )
  }, [sortedSessions])

  const trendSnapshot = useMemo(
    () => deriveTrendSnapshot(recentSessions),
    [recentSessions]
  )

  const showOnboarding =
    !sessionsLoading && !sessionsError && sortedSessions.length === 0

  const dismissActiveSession = () => {
    clearStoredActiveSession()
    setActiveSession(null)
  }

  const handleAnalyticsNavigation = () => dismissActiveSession()

  const createSession = async () => {
    setCreating(true)
    setError('')

    try {
      const response = await apiFetch('/api/sessions', {
        method: 'POST',
        accessToken,
        body: JSON.stringify({
          session_type: sessionType,
          session_title: sessionTitle.trim(),
          coaching_intensity: coachingIntensity,
          media_provider: 'livekit',
        }),
      })

      if (!response.ok) throw new Error('Failed to create session')

      const data = (await response.json()) as SessionCreateResponse
      setSessionInfo(data)
      setCopiedStudentLink(false)
      saveActiveSession(data.session_id, data.tutor_token)
      setActiveSession(getActiveSession())
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to create session'
      )
    } finally {
      setCreating(false)
    }
  }

  const enterCreatedSession = () => {
    if (!sessionInfo) return
    router.push(
      buildSessionHref(sessionInfo.session_id, sessionInfo.tutor_token)
    )
  }

  const copyStudentLink = async () => {
    if (!sessionInfo || typeof window === 'undefined') return
    const link = `${window.location.origin}${buildSessionHref(
      sessionInfo.session_id,
      sessionInfo.student_token
    )}`
    try {
      await writeToClipboard(link)
      setCopiedStudentLink(true)
      toast.success('Student link copied!')
    } catch {
      setError('Failed to copy link')
      toast.error('Failed to copy link')
    }
  }

  const joinSession = () => {
    const sid = joinSessionId.trim()
    const tok = joinToken.trim()
    if (!sid || !tok) return
    router.push(buildSessionHref(sid, tok))
  }

  const roleLabel =
    userRole === 'student'
      ? 'Student'
      : userRole === 'guest'
        ? 'Guest'
        : 'Tutor'

  return (
    <main className="min-h-screen bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] text-slate-100">
      <div className="mx-auto flex max-w-[1100px] flex-col gap-10 px-6 py-12 lg:gap-14 lg:px-8 lg:py-16">
        {/* ── Hero ── */}
        <section className="relative overflow-hidden rounded-3xl border border-white/[0.06] bg-gradient-to-br from-[#1e2545]/90 to-[#252b4a]/80 p-8 shadow-[0_32px_120px_rgba(10,14,40,0.7)] md:p-12">
          {/* Top bar */}
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                <Image
                  src="/nerdy-logo.svg"
                  alt="Nerdy"
                  width={72}
                  height={18}
                  className="h-[18px] w-auto"
                  priority
                />
              </div>
              <span className="hidden text-xs uppercase tracking-[0.18em] text-[#556080] sm:inline">
                A Varsity Tutors Platform
              </span>
            </div>
            <UserMenu />
          </div>

          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-[#4a5fff]/30 bg-[#4a5fff]/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-[#8b9aff]">
                {roleLabel} workspace
              </div>
              <h1 className="text-4xl font-bold tracking-tight text-white md:text-5xl">
                <span className="font-serif-accent italic text-accent-gradient">
                  Live
                </span>{' '}
                Session Analysis
              </h1>
              <p className="text-xl font-medium text-white/90">
                {userName ? `Welcome back, ${userName}` : 'Welcome'}
              </p>
              <p className="max-w-xl text-base leading-7 text-[#8896b3]">
                {isStudent
                  ? 'Join your tutoring session using the link your tutor shared.'
                  : 'Launch a new room, join an active session, and review analytics — all from one dashboard.'}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {/* Identity card */}
              <div className="rounded-2xl border border-white/8 bg-[#1e2545]/70 px-5 py-5">
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b7ba0]">
                  Signed in as
                </p>
                <p className="mt-3 text-xl font-semibold text-white">
                  {userName || 'Guest'}
                </p>
                {userEmail ? (
                  <p className="mt-1 truncate text-sm text-[#6b7ba0]">
                    {userEmail}
                  </p>
                ) : null}
                <span className="mt-2 inline-flex rounded-full border border-white/10 bg-[#2a3158] px-2 py-0.5 text-xs text-[#8896b3]">
                  {roleLabel}
                </span>
              </div>

              {!isStudent ? (
                <Link
                  href="/analytics"
                  onClick={handleAnalyticsNavigation}
                  className="group rounded-2xl border border-white/8 bg-[#1e2545]/70 px-5 py-5 transition hover:border-[#7b6ef6]/30 hover:bg-[#252d55]/80"
                >
                  <p className="text-xs uppercase tracking-[0.22em] text-[#6b7ba0]">
                    Analytics
                  </p>
                  <p className="mt-3 text-xl font-semibold text-white">
                    Session portfolio
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[#6b7ba0]">
                    Compare sessions, inspect trends, and drill into flagged
                    moments.
                  </p>
                  <span className="mt-3 inline-flex text-sm font-medium text-accent-gradient transition group-hover:translate-x-1">
                    Browse analytics →
                  </span>
                </Link>
              ) : null}
            </div>
          </div>
        </section>

        {/* ── Active session banner ── */}
        {activeSession && !isStudent ? (
          <section
            data-testid="active-session-banner"
            className="rounded-2xl border border-emerald-400/20 bg-emerald-500/[0.08] p-5"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-xs uppercase tracking-[0.22em] text-emerald-200">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Active Session
                </div>
                <h2 className="mt-3 text-2xl font-semibold text-white">
                  Join your tutor room
                </h2>
                <p className="mt-1 text-sm text-emerald-100/80">
                  Ref {truncateSessionId(activeSession.session_id)} ·{' '}
                  {formatBannerTimestamp(activeSession.created_at)}
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() =>
                    router.push(
                      buildSessionHref(
                        activeSession.session_id,
                        activeSession.tutor_token
                      )
                    )
                  }
                  className="rounded-2xl bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-[#1a1f3a] transition hover:bg-emerald-300"
                >
                  Join
                </button>
                <button
                  onClick={dismissActiveSession}
                  className="rounded-2xl border border-emerald-400/25 px-5 py-2.5 text-sm font-medium text-emerald-200 transition hover:bg-emerald-400/10"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {/* ── Body ── */}
        {isStudent ? (
          <StudentDashboard
            joinSessionId={joinSessionId}
            joinToken={joinToken}
            onJoinSessionIdChange={setJoinSessionId}
            onJoinTokenChange={setJoinToken}
            onJoin={joinSession}
          />
        ) : showOnboarding ? (
          /* Onboarding — no sessions yet */
          <div className="mx-auto w-full max-w-3xl space-y-6">
            <section className="rounded-2xl border border-white/8 bg-[#1e2545]/60 p-6 text-center backdrop-blur md:p-8">
              <p className="text-xs uppercase tracking-[0.24em] text-[#8896b3]">
                New workspace
              </p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">
                Start your{' '}
                <span className="font-serif-accent italic text-accent-gradient">
                  first
                </span>{' '}
                session
              </h2>
              <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-[#6b7ba0]">
                No sessions saved yet. Create a room, teach live, then return
                for the post-session review.
              </p>
            </section>

            <SessionCreationCard
              large
              sessionType={sessionType}
              sessionTitle={sessionTitle}
              coachingIntensity={coachingIntensity}
              creating={creating}
              copiedStudentLink={copiedStudentLink}
              error={error}
              sessionInfo={sessionInfo}
              onSessionTypeChange={setSessionType}
              onSessionTitleChange={setSessionTitle}
              onCoachingIntensityChange={setCoachingIntensity}
              onCreate={createSession}
              onEnterSession={enterCreatedSession}
              onCopyStudentLink={copyStudentLink}
            />

            <JoinSessionCard
              joinSessionId={joinSessionId}
              joinToken={joinToken}
              onJoinSessionIdChange={setJoinSessionId}
              onJoinTokenChange={setJoinToken}
              onJoin={joinSession}
            />
          </div>
        ) : (
          /* ── Tutor main view ── */
          <div className="grid gap-8 xl:grid-cols-[1.35fr_0.85fr] xl:gap-10">
            {/* Left column: history */}
            <div className="space-y-8">
              {/* Summary stats */}
              <section>
                <div className="mb-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-[#8896b3]">
                    Recent sessions
                  </p>
                  <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white">
                    Session{' '}
                    <span className="font-serif-accent italic text-accent-gradient">
                      history
                    </span>
                  </h2>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <StatCard
                    label="Total"
                    value={String(sortedSessions.length)}
                    detail="Saved sessions"
                  />
                  <StatCard
                    label="Avg engagement"
                    value={formatScore(averageEngagement)}
                    detail="Across all sessions"
                  />
                  <StatCard
                    label="Trend"
                    value={getTrendLabel(trendSnapshot.engagement)}
                    detail="Recent trajectory"
                    tone={getTrendTone(trendSnapshot.engagement)}
                  />
                </div>
              </section>

              {/* Session list */}
              {sessionsLoading ? (
                <div className="rounded-2xl border border-white/8 bg-[#1e2545]/60 p-8 text-[#6b7ba0]">
                  Loading sessions…
                </div>
              ) : sessionsError ? (
                <div className="rounded-2xl border border-rose-400/25 bg-rose-500/10 p-8 text-rose-200">
                  {sessionsError}
                </div>
              ) : (
                <section className="space-y-3">
                  {visibleSessions.map((s) => {
                    const health = getSessionHealth(s)
                    return (
                      <Link
                        key={s.session_id}
                        href={`/analytics/${encodeURIComponent(s.session_id)}`}
                        onClick={handleAnalyticsNavigation}
                        className="group block rounded-2xl border border-white/[0.06] bg-[#1e2545]/50 p-5 transition hover:-translate-y-0.5 hover:border-[#7b6ef6]/25 hover:bg-[#252d55]/70 hover:shadow-[0_8px_40px_rgba(123,110,246,0.08)]"
                      >
                        <div className="flex flex-col gap-3">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span
                                  className={`rounded-full border px-2.5 py-0.5 text-xs uppercase tracking-[0.16em] ${toneClasses(health.tone)}`}
                                >
                                  {health.label}
                                </span>
                                <span className="rounded-full border border-white/8 bg-white/[0.04] px-2.5 py-0.5 text-xs text-[#8896b3]">
                                  {getSessionTypeLabel(s.session_type)}
                                </span>
                              </div>
                              <h3 className="mt-3 text-xl font-semibold text-white">
                                {s.session_title ||
                                  new Date(s.start_time).toLocaleString(
                                    undefined,
                                    {
                                      dateStyle: 'medium',
                                      timeStyle: 'short',
                                    }
                                  )}
                              </h3>
                              <p className="mt-1 text-sm text-[#6b7ba0]">
                                {formatMinutes(s.duration_seconds)} ·{' '}
                                {s.flagged_moments.length} flagged ·{' '}
                                {s.nudges_sent} nudge
                                {s.nudges_sent === 1 ? '' : 's'}
                              </p>
                            </div>

                            <div className="text-left sm:text-right">
                              <p className="text-xs uppercase tracking-[0.18em] text-[#6b7ba0]">
                                Engagement
                              </p>
                              <p className="mt-1 text-3xl font-semibold text-white">
                                {formatScore(s.engagement_score)}
                              </p>
                            </div>
                          </div>

                          <p className="text-sm leading-6 text-[#8896b3]">
                            {health.summary}
                          </p>

                          <span className="inline-flex text-sm font-medium text-[#7b6ef6] opacity-0 transition group-hover:opacity-100 group-hover:translate-x-1">
                            Open review →
                          </span>
                        </div>
                      </Link>
                    )
                  })}

                  {/* Show all / collapse toggle */}
                  {sortedSessions.length > VISIBLE_SESSION_COUNT && (
                    <div className="pt-2 text-center">
                      <button
                        type="button"
                        onClick={() => setShowAllSessions((v) => !v)}
                        className="rounded-full border border-white/10 bg-white/[0.04] px-5 py-2 text-sm font-medium text-[#8896b3] transition hover:bg-white/[0.08] hover:text-white"
                      >
                        {showAllSessions
                          ? 'Show less'
                          : `Show all ${sortedSessions.length} sessions`}
                      </button>
                    </div>
                  )}
                </section>
              )}
            </div>

            {/* Right column: create + join */}
            <aside className="space-y-6">
              <SessionCreationCard
                sessionType={sessionType}
                sessionTitle={sessionTitle}
                coachingIntensity={coachingIntensity}
                creating={creating}
                copiedStudentLink={copiedStudentLink}
                error={error}
                sessionInfo={sessionInfo}
                onSessionTypeChange={setSessionType}
                onSessionTitleChange={setSessionTitle}
                onCoachingIntensityChange={setCoachingIntensity}
                onCreate={createSession}
                onEnterSession={enterCreatedSession}
                onCopyStudentLink={copyStudentLink}
              />

              <JoinSessionCard
                joinSessionId={joinSessionId}
                joinToken={joinToken}
                onJoinSessionIdChange={setJoinSessionId}
                onJoinTokenChange={setJoinToken}
                onJoin={joinSession}
              />
            </aside>
          </div>
        )}
      </div>
    </main>
  )
}

export default function Home() {
  return (
    <AuthGuard>
      <HomeContent />
    </AuthGuard>
  )
}
