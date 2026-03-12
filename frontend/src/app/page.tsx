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
import {
  clearActiveSession as clearStoredActiveSession,
  getActiveSession,
  type ActiveSession,
  saveActiveSession,
} from '@/lib/active-session'

type SessionCreateResponse = {
  session_id: string
  session_title?: string
  tutor_token: string
  student_token: string
  media_provider?: 'custom_webrtc' | 'livekit'
  livekit_room_name?: string | null
  coaching_intensity?: string
}

type AnalyticsTone = 'emerald' | 'amber' | 'rose' | 'slate' | 'violet'

const PANEL_CLASSES =
  'rounded-[28px] border border-white/10 bg-white/5 shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur'
const INPUT_CLASSES =
  'w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400'
const SELECT_CLASSES = `${INPUT_CLASSES} appearance-none`

function toneClasses(tone: AnalyticsTone) {
  const styles = {
    emerald: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
    amber: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
    rose: 'border-rose-400/30 bg-rose-400/10 text-rose-100',
    slate: 'border-white/15 bg-white/5 text-slate-200',
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
  const mutedText = tone === 'slate' ? 'text-slate-400' : 'text-white/70'
  const detailText = tone === 'slate' ? 'text-slate-400' : 'text-white/80'

  return (
    <div className={`${PANEL_CLASSES} p-5 ${tone === 'slate' ? '' : toneClasses(tone)}`}>
      <p className={`text-xs uppercase tracking-[0.22em] ${mutedText}`}>{label}</p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className={`mt-2 text-sm ${detailText}`}>{detail}</p>
    </div>
  )
}

function SessionCreationCard({
  sessionType,
  coachingIntensity,
  creating,
  copiedStudentLink,
  error,
  sessionInfo,
  large = false,
  onSessionTypeChange,
  onCoachingIntensityChange,
  onCreate,
  onEnterSession,
  onCopyStudentLink,
}: {
  sessionType: string
  coachingIntensity: string
  creating: boolean
  copiedStudentLink: boolean
  error: string
  sessionInfo: SessionCreateResponse | null
  large?: boolean
  onSessionTypeChange: (value: string) => void
  onCoachingIntensityChange: (value: string) => void
  onCreate: () => void
  onEnterSession: () => void
  onCopyStudentLink: () => Promise<void>
}) {
  const panelPadding = large ? 'p-8 md:p-10' : 'p-6'
  const titleClass = large ? 'text-3xl' : 'text-2xl'
  const studentJoinLink =
    sessionInfo && typeof window !== 'undefined'
      ? `${window.location.origin}${buildSessionHref(sessionInfo.session_id, sessionInfo.student_token)}`
      : ''

  return (
    <section className={`${PANEL_CLASSES} ${panelPadding}`}>
      <div className="flex flex-col gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
            Session creation
          </p>
          <h2 className={`mt-2 font-semibold tracking-tight text-white ${titleClass}`}>
            {large ? 'Start your first tutoring session' : 'Create a new session'}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
            Create a live tutoring room, share the student link, and return here later for the post-session analytics review.
          </p>
        </div>

        {!sessionInfo ? (
          <div className="space-y-4">
            <div>
              <label
                htmlFor="session-type"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Session type
              </label>
              <select
                id="session-type"
                data-testid="session-type-select"
                value={sessionType}
                onChange={(event) => onSessionTypeChange(event.target.value)}
                className={SELECT_CLASSES}
              >
                <option value="general">General tutoring</option>
                <option value="lecture">Lecture / explanation</option>
                <option value="practice">Practice / problem solving</option>
                <option value="discussion">Discussion / Socratic</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="coaching-intensity"
                className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
              >
                Coaching intensity
              </label>
              <select
                id="coaching-intensity"
                data-testid="coaching-intensity-select"
                value={coachingIntensity}
                onChange={(event) => onCoachingIntensityChange(event.target.value)}
                className={SELECT_CLASSES}
              >
                <option value="off">Off</option>
                <option value="subtle">Subtle</option>
                <option value="normal">Normal</option>
                <option value="aggressive">Aggressive</option>
              </select>
            </div>

            <input type="hidden" data-testid="media-provider-select" value="livekit" />

            <button
              data-testid="create-session-button"
              onClick={onCreate}
              disabled={creating}
              className="w-full rounded-2xl bg-[#0066FF] px-4 py-3 text-sm font-medium text-white transition hover:bg-[#3385FF] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {creating ? 'Creating session…' : 'Create Session'}
            </button>
          </div>
        ) : (
          <div data-testid="session-created-card" className="space-y-4">
            <div className="rounded-3xl border border-emerald-400/30 bg-emerald-400/10 p-4 text-emerald-50">
              <p className="text-sm font-semibold text-emerald-100">Session created and ready to enter.</p>
              <p data-testid="created-session-id" className="mt-2 text-xs text-emerald-200/90">
                Session ID: {sessionInfo.session_id}
              </p>
              <p className="mt-3 text-sm leading-6 text-emerald-50/90">
                You are the tutor for this room. Share the student link below so the student joins the clean call view without tutor coaching overlays.
              </p>
            </div>

            <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-white">Student join link</p>
                <button
                  type="button"
                  onClick={() => {
                    void onCopyStudentLink()
                  }}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200 transition hover:bg-white/10"
                >
                  {copiedStudentLink ? 'Copied' : 'Copy link'}
                </button>
              </div>
              <code
                data-testid="student-join-link"
                className="block break-all rounded-2xl bg-slate-900 px-3 py-3 text-xs text-sky-100"
              >
                {studentJoinLink}
              </code>
            </div>

            <button
              data-testid="join-as-tutor-button"
              onClick={onEnterSession}
              className="w-full rounded-2xl bg-white px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-slate-100"
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
    <section className={`${PANEL_CLASSES} p-6`}>
      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Universal rejoin</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">
        Join Session
      </h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">
        Enter a session ID and token to join as tutor or student. Use this to rejoin an active session from another device, or to join as a student.
      </p>

      <div className="mt-5 space-y-4">
        <div>
          <label
            htmlFor="join-session-id"
            className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
          >
            Session ID
          </label>
          <input
            id="join-session-id"
            type="text"
            placeholder="Session ID"
            value={joinSessionId}
            onChange={(event) => onJoinSessionIdChange(event.target.value)}
            className={INPUT_CLASSES}
          />
        </div>

        <div>
          <label
            htmlFor="join-session-token"
            className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-400"
          >
            Token
          </label>
          <input
            id="join-session-token"
            type="text"
            placeholder="Join token"
            value={joinToken}
            onChange={(event) => onJoinTokenChange(event.target.value)}
            className={INPUT_CLASSES}
          />
        </div>

        <button
          onClick={onJoin}
          disabled={!joinSessionId.trim() || !joinToken.trim()}
          className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Join Session
        </button>
      </div>
    </section>
  )
}

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
      <section className="rounded-[28px] border border-white/10 bg-white/5 p-6 text-center shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur md:p-8">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
          Student workspace
        </p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">
          Join a tutoring session
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-400">
          Ask your tutor to share the session join link, or paste a session ID and token below to join directly.
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

function HomeContent() {
  const router = useRouter()
  const { data: session } = useSession()

  const userName = session?.user?.name ?? ''
  const userEmail = (session?.user as { email?: string } | undefined)?.email ?? ''
  const userRole = (session?.user as { role?: string } | undefined)?.role ?? 'tutor'
  const accessToken = (session?.user as { accessToken?: string } | undefined)?.accessToken
  const isStudent = userRole === 'student'

  const [sessionType, setSessionType] = useState('general')
  const [coachingIntensity, setCoachingIntensity] = useState('normal')
  const [joinToken, setJoinToken] = useState('')
  const [joinSessionId, setJoinSessionId] = useState('')
  const [creating, setCreating] = useState(false)
  const [copiedStudentLink, setCopiedStudentLink] = useState(false)
  const [error, setError] = useState('')
  const [sessionInfo, setSessionInfo] = useState<SessionCreateResponse | null>(null)
  const [activeSession, setActiveSession] = useState<ActiveSession | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [sessionsError, setSessionsError] = useState('')

  useEffect(() => {
    if (isStudent) {
      // Students never use tutor tokens from localStorage. Clear any stale
      // active_session entry so it doesn't show up if they later switch roles
      // or share a browser with a tutor.
      clearStoredActiveSession()
      setActiveSession(null)
    } else {
      setActiveSession(getActiveSession())
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStudent])

  // Fetch sessions using authenticated API client.
  // No tutor_id query param needed — backend filters by the JWT identity.
  useEffect(() => {
    let cancelled = false

    setSessionsLoading(true)
    setSessionsError('')

    apiFetch('/api/analytics/sessions', { accessToken })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Failed to load session history')
        }
        return response.json()
      })
      .then((data) => {
        if (!cancelled) {
          setSessions(Array.isArray(data) ? data : [])
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setSessionsError(
            fetchError instanceof Error
              ? fetchError.message
              : 'Failed to load session history'
          )
          setSessions([])
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSessionsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [accessToken])

  const sortedSessions = useMemo(() => {
    return [...sessions].sort(
      (a, b) =>
        new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
    )
  }, [sessions])

  const recentSessions = useMemo(() => sortedSessions.slice(0, 8), [sortedSessions])

  const averageEngagement = useMemo(() => {
    if (sortedSessions.length === 0) return 0
    const total = sortedSessions.reduce(
      (sum, s) => sum + s.engagement_score,
      0
    )
    return total / sortedSessions.length
  }, [sortedSessions])

  const trendSnapshot = useMemo(
    () => deriveTrendSnapshot(recentSessions),
    [recentSessions]
  )

  const showOnboarding = !sessionsLoading && !sessionsError && sortedSessions.length === 0

  const dismissActiveSession = () => {
    clearStoredActiveSession()
    setActiveSession(null)
  }

  const handleAnalyticsNavigation = () => {
    dismissActiveSession()
  }

  const createSession = async () => {
    setCreating(true)
    setError('')

    try {
      const response = await apiFetch('/api/sessions', {
        method: 'POST',
        accessToken,
        body: JSON.stringify({
          session_type: sessionType,
          coaching_intensity: coachingIntensity,
          media_provider: 'livekit',
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to create session')
      }

      const data = (await response.json()) as SessionCreateResponse
      setSessionInfo(data)
      setCopiedStudentLink(false)
      saveActiveSession(data.session_id, data.tutor_token)
      setActiveSession(getActiveSession())
    } catch (createError) {
      setError(
        createError instanceof Error
          ? createError.message
          : 'Failed to create session'
      )
    } finally {
      setCreating(false)
    }
  }

  const enterCreatedSession = () => {
    if (!sessionInfo) return
    router.push(buildSessionHref(sessionInfo.session_id, sessionInfo.tutor_token))
  }

  const copyStudentLink = async () => {
    if (!sessionInfo || typeof window === 'undefined') return

    const studentJoinLink = `${window.location.origin}${buildSessionHref(
      sessionInfo.session_id,
      sessionInfo.student_token
    )}`

    if (!studentJoinLink || !navigator.clipboard?.writeText) {
      return
    }

    try {
      await navigator.clipboard.writeText(studentJoinLink)
      setCopiedStudentLink(true)
    } catch {
      setError('Failed to copy student link')
    }
  }

  const joinSession = () => {
    const normalizedSessionId = joinSessionId.trim()
    const normalizedToken = joinToken.trim()

    if (!normalizedSessionId || !normalizedToken) return

    router.push(buildSessionHref(normalizedSessionId, normalizedToken))
  }

  // Role label for display
  const roleLabel =
    userRole === 'student' ? 'Student' : userRole === 'guest' ? 'Guest' : 'Tutor'

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-10 lg:px-8">
        {/* Hero section */}
        <section className="relative overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(0,102,255,0.22),_transparent_32%),radial-gradient(circle_at_top_right,_rgba(255,107,53,0.16),_transparent_30%),linear-gradient(180deg,_rgba(10,22,40,0.97),_rgba(2,6,23,0.98))] p-8 shadow-[0_28px_120px_rgba(2,6,23,0.55)]">
          {/* UserMenu in the hero section top-right */}
          <div className="mb-4 flex justify-end">
            <UserMenu />
          </div>
          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.24em] text-slate-300">
                {roleLabel} workspace
              </div>
              <div>
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <div className="rounded-full border border-white/10 bg-white/5 px-3 py-2">
                    <Image
                      src="/nerdy-logo.svg"
                      alt="Nerdy"
                      width={84}
                      height={22}
                      className="h-5 w-auto"
                      priority
                    />
                  </div>
                  <span className="text-xs text-slate-500 uppercase tracking-[0.18em]">
                    A Varsity Tutors Platform
                  </span>
                </div>
                <h1 className="text-4xl font-semibold tracking-tight text-white md:text-5xl">
                  Live Session Analysis
                </h1>
                <p className="mt-4 text-2xl font-semibold text-slate-100">
                  {userName ? `Welcome back, ${userName}` : 'Welcome'}
                </p>
                <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
                  {isStudent
                    ? 'Join your tutoring session below using the link your tutor shared with you.'
                    : 'Launch a new tutoring room, rejoin an active session from this browser, and jump straight into recent analytics reviews from one dark-theme dashboard.'}
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {/* Auth identity card */}
              <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Signed in as
                </p>
                <p className="mt-3 text-xl font-semibold text-white">
                  {userName || 'Guest'}
                </p>
                {userEmail ? (
                  <p className="mt-1 truncate text-sm text-slate-400">{userEmail}</p>
                ) : null}
                <span className="mt-2 inline-flex rounded-full border border-white/10 bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                  {roleLabel}
                </span>
              </div>

              {!isStudent ? (
                <Link
                  href="/analytics"
                  onClick={handleAnalyticsNavigation}
                  className="rounded-3xl border border-white/10 bg-white/5 px-5 py-5 transition hover:bg-white/10"
                >
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Analytics portfolio
                  </p>
                  <p className="mt-3 text-xl font-semibold text-white">
                    Review every saved session
                  </p>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    Open the full analytics view to compare sessions, inspect trends, and drill into flagged moments.
                  </p>
                  <span className="mt-4 inline-flex text-sm font-medium text-sky-300">
                    Browse analytics →
                  </span>
                </Link>
              ) : null}
            </div>
          </div>
        </section>

        {/* Active session banner — tutors/guests only; students join via links,
            not tutor tokens cached in localStorage from a previous session */}
        {activeSession && !isStudent ? (
          <section
            data-testid="active-session-banner"
            className="rounded-[28px] border border-emerald-400/30 bg-emerald-500/10 p-5 shadow-[0_20px_70px_rgba(16,185,129,0.12)]"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-3 py-1 text-xs uppercase tracking-[0.22em] text-emerald-100">
                  Active Session
                </div>
                <h2 className="mt-3 text-2xl font-semibold text-white">
                  Rejoin your saved tutor room
                </h2>
                <p className="mt-2 text-sm font-medium text-emerald-100">
                  Session ID {truncateSessionId(activeSession.session_id)}
                </p>
                <p className="mt-2 text-sm leading-6 text-emerald-50/90">
                  Saved from this browser at {formatBannerTimestamp(activeSession.created_at)}. This shortcut is convenient here, but the manual join form below still matters for other browsers, devices, and students.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <button
                  onClick={() => {
                    router.push(
                      buildSessionHref(
                        activeSession.session_id,
                        activeSession.tutor_token
                      )
                    )
                  }}
                  className="rounded-2xl bg-emerald-400 px-5 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300"
                >
                  Rejoin Session
                </button>
                <button
                  onClick={dismissActiveSession}
                  className="rounded-2xl border border-emerald-300/30 bg-transparent px-5 py-3 text-sm font-medium text-emerald-100 transition hover:bg-emerald-300/10"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {/* Student view: join only */}
        {isStudent ? (
          <StudentDashboard
            joinSessionId={joinSessionId}
            joinToken={joinToken}
            onJoinSessionIdChange={setJoinSessionId}
            onJoinTokenChange={setJoinToken}
            onJoin={joinSession}
          />
        ) : showOnboarding ? (
          /* Tutor onboarding — no sessions yet */
          <div className="mx-auto w-full max-w-3xl space-y-6">
            <section className="rounded-[28px] border border-white/10 bg-white/5 p-6 text-center shadow-[0_24px_80px_rgba(2,6,23,0.28)] backdrop-blur md:p-8">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                New tutor workspace
              </p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">
                Start your first tutoring session
              </h2>
              <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                No completed sessions stored yet. Create a room, teach live, then return here for the saved post-session review.
              </p>
            </section>

            <SessionCreationCard
              large
              sessionType={sessionType}
              coachingIntensity={coachingIntensity}
              creating={creating}
              copiedStudentLink={copiedStudentLink}
              error={error}
              sessionInfo={sessionInfo}
              onSessionTypeChange={setSessionType}
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
          /* Tutor main view — has sessions */
          <div className="grid gap-6 xl:grid-cols-[1.35fr_0.85fr]">
            <div className="space-y-6">
              <section>
                <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                      Recent sessions
                    </p>
                    <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white">
                      Session history
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      Sessions linked to your account. Open any card to review the full analytics detail page.
                    </p>
                  </div>
                  <p className="text-sm text-slate-500">
                    Showing the {recentSessions.length} most recent completed session{recentSessions.length === 1 ? '' : 's'}.
                  </p>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <StatCard
                    label="Total sessions"
                    value={String(sortedSessions.length)}
                    detail="Saved completed sessions for your account."
                  />
                  <StatCard
                    label="Average engagement"
                    value={formatScore(averageEngagement)}
                    detail="Across the stored sessions linked to your account."
                  />
                  <StatCard
                    label="Engagement trend"
                    value={getTrendLabel(trendSnapshot.engagement)}
                    detail="Derived from the recent session history trend line."
                    tone={getTrendTone(trendSnapshot.engagement)}
                  />
                </div>
              </section>

              {sessionsLoading ? (
                <section className={`${PANEL_CLASSES} p-8 text-slate-300`}>
                  Loading recent sessions…
                </section>
              ) : sessionsError ? (
                <section className="rounded-[28px] border border-rose-400/30 bg-rose-500/10 p-8 text-rose-100">
                  {sessionsError}
                </section>
              ) : (
                <section className="space-y-4">
                  {recentSessions.map((s) => {
                    const health = getSessionHealth(s)
                    return (
                      <Link
                        key={s.session_id}
                        href={`/analytics/${encodeURIComponent(s.session_id)}`}
                        onClick={handleAnalyticsNavigation}
                        className="group block rounded-[28px] border border-white/10 bg-white/5 p-5 transition hover:-translate-y-1 hover:border-sky-300/30 hover:bg-white/10"
                      >
                        <div className="flex flex-col gap-4">
                          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span
                                  className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] ${toneClasses(health.tone)}`}
                                >
                                  {health.label}
                                </span>
                                <span className="rounded-full border border-white/10 bg-slate-950/50 px-3 py-1 text-xs text-slate-300">
                                  {getSessionTypeLabel(s.session_type)}
                                </span>
                              </div>
                              <h3 className="mt-4 text-2xl font-semibold text-white">
                                {new Date(s.start_time).toLocaleString(undefined, {
                                  dateStyle: 'medium',
                                  timeStyle: 'short',
                                })}
                              </h3>
                              <p className="mt-2 text-sm text-slate-400">
                                Duration {formatMinutes(s.duration_seconds)} · Session {truncateSessionId(s.session_id)}
                              </p>
                            </div>

                            <div className="text-left sm:text-right">
                              <p className="text-sm text-slate-400">Engagement</p>
                              <p className="mt-2 text-4xl font-semibold text-white">
                                {formatScore(s.engagement_score)}
                              </p>
                            </div>
                          </div>

                          <p className="text-sm leading-6 text-slate-300">
                            {health.summary}
                          </p>

                          <div className="flex items-center justify-between gap-4 text-sm text-slate-400">
                            <span>
                              {s.flagged_moments.length} flagged moment{s.flagged_moments.length === 1 ? '' : 's'} · {s.nudges_sent} live nudge{s.nudges_sent === 1 ? '' : 's'}
                            </span>
                            <span className="text-slate-200 transition group-hover:translate-x-1">
                              Open analytics →
                            </span>
                          </div>
                        </div>
                      </Link>
                    )
                  })}
                </section>
              )}
            </div>

            <aside className="space-y-6">
              <SessionCreationCard
                sessionType={sessionType}
                coachingIntensity={coachingIntensity}
                creating={creating}
                copiedStudentLink={copiedStudentLink}
                error={error}
                sessionInfo={sessionInfo}
                onSessionTypeChange={setSessionType}
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
