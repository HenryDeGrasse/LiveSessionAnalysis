'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import { apiFetch } from '@/lib/api-client'
import { AuthGuard } from '@/components/auth/AuthGuard'
import type { SessionSummary } from '@/lib/types'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import {
  deriveActionQueue,
  deriveDashboardOverview,
  deriveTrendSnapshot,
  formatMinutes,
  formatPercent,
  formatScore,
  getSessionDisplayTitle,
  getSessionHealth,
  getSessionTypeLabel,
  getTrendLabel,
  getTrendTone,
} from '@/lib/analytics'
import {
  getAnalyticsPortfolioDescription,
  getAnalyticsPortfolioHeading,
} from '@/lib/analytics-view'

type FocusMetric = 'engagement' | 'studentEye' | 'tutorTalk' | 'interruptions'

const FOCUS_METRICS: Array<{
  key: FocusMetric
  label: string
  description: string
  color: string
}> = [
  {
    key: 'engagement',
    label: 'Engagement',
    description: 'Average engagement score per session.',
    color: '#8B5CF6',
  },
  {
    key: 'studentEye',
    label: 'Student camera-facing',
    description: 'Average student visual attention / camera-facing signal.',
    color: '#22C55E',
  },
  {
    key: 'tutorTalk',
    label: 'Tutor talk share',
    description: 'How much of the session the tutor occupied vocally.',
    color: '#38BDF8',
  },
  {
    key: 'interruptions',
    label: 'Interruptions',
    description: 'Cumulative interruption count per session.',
    color: '#F97316',
  },
]

function toneClasses(tone: 'emerald' | 'amber' | 'rose' | 'slate' | 'violet') {
  const styles = {
    emerald: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
    amber: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
    rose: 'border-rose-400/30 bg-rose-400/10 text-rose-100',
    slate: 'border-white/15 bg-white/5 text-slate-200',
    violet: 'border-violet-400/30 bg-violet-400/10 text-violet-100',
  }

  return styles[tone]
}

function StatCard({
  title,
  value,
  detail,
  testId,
}: {
  title: string
  value: string
  detail: string
  testId: string
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-[0_24px_80px_rgba(15,23,42,0.28)] backdrop-blur"
    >
      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
        {title}
      </p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm text-slate-400">{detail}</p>
    </div>
  )
}

function TrendBadge({
  label,
  trend,
}: {
  label: string
  trend: ReturnType<typeof deriveTrendSnapshot>['engagement']
}) {
  const arrows = {
    improving: '↗',
    stable: '→',
    declining: '↘',
  }

  return (
    <div
      className={`rounded-2xl border px-4 py-3 ${toneClasses(getTrendTone(trend))}`}
    >
      <p className="text-xs uppercase tracking-[0.2em] opacity-80">{label}</p>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-lg font-semibold">{getTrendLabel(trend)}</span>
        <span className="text-lg">{arrows[trend]}</span>
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  const { data: authSession, status: authStatus } = useSession()
  const userRole = authSession?.user?.role
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedType, setSelectedType] = useState('all')
  const [focusMetric, setFocusMetric] = useState<FocusMetric>('engagement')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    // Do not issue any request while NextAuth is still resolving the session.
    // Firing before status is resolved sends an unauthenticated request that
    // the backend correctly rejects (returns []) but causes a misleading flash
    // of "no sessions" before the real authenticated fetch completes.
    if (authStatus === 'loading') return

    let cancelled = false

    apiFetch('/api/analytics/sessions', {
      accessToken: authSession?.user?.accessToken,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Failed to load analytics sessions')
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
          setError(
            fetchError instanceof Error
              ? fetchError.message
              : 'Failed to load analytics sessions'
          )
          setSessions([])
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, authSession?.user?.accessToken])

  function openDeleteConfirm(sessionId: string, event: React.MouseEvent) {
    event.preventDefault()
    event.stopPropagation()
    setDeleteError('')
    setDeleteConfirm(sessionId)
  }

  async function confirmDelete() {
    if (!deleteConfirm) return
    setDeleting(true)
    setDeleteError('')
    try {
      const response = await apiFetch(
        `/api/analytics/sessions/${deleteConfirm}`,
        { method: 'DELETE', accessToken: authSession?.user?.accessToken }
      )
      if (!response.ok) {
        throw new Error('Failed to delete session')
      }
      setSessions((prev) => prev.filter((s) => s.session_id !== deleteConfirm))
      setDeleteConfirm(null)
    } catch {
      setDeleteError('Failed to delete session. Please try again.')
    } finally {
      setDeleting(false)
    }
  }

  const filteredSessions = useMemo(() => {
    return sessions.filter((session) => {
      return selectedType === 'all' || session.session_type === selectedType
    })
  }, [selectedType, sessions])

  const overview = useMemo(
    () => deriveDashboardOverview(filteredSessions),
    [filteredSessions]
  )
  const trendSnapshot = useMemo(
    () => deriveTrendSnapshot(filteredSessions),
    [filteredSessions]
  )
  const actionQueue = useMemo(
    () => deriveActionQueue(filteredSessions),
    [filteredSessions]
  )

  const chartData = useMemo(() => {
    return [...filteredSessions]
      .sort(
        (a, b) =>
          new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
      )
      .map((session) => ({
        session_id: session.session_id,
        start_time: session.start_time,
        label: new Date(session.start_time).toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
        }),
        engagement: session.engagement_score,
        studentEye: (session.avg_eye_contact.student || 0) * 100,
        tutorTalk: (session.talk_time_ratio.tutor || 0) * 100,
        interruptions: session.total_interruptions,
      }))
  }, [filteredSessions])

  const focus = FOCUS_METRICS.find((metric) => metric.key === focusMetric)!
  const emptyForFilter = !loading && sessions.length > 0 && filteredSessions.length === 0

  return (
    <AuthGuard>
    <main className="min-h-screen bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-8 px-6 py-10 lg:px-8">
        <section
          data-testid="analytics-dashboard"
          className="relative overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_32%),radial-gradient(circle_at_top_right,_rgba(139,92,246,0.22),_transparent_30%),linear-gradient(180deg,_rgba(15,23,42,0.96),_rgba(2,6,23,0.98))] p-8 shadow-[0_28px_120px_rgba(2,6,23,0.6)]"
        >
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.24em] text-slate-300">
                {userRole === 'student' ? 'Student session history' : 'Tutor review room'}
              </div>
              <div>
                <h1 className="text-4xl font-semibold tracking-tight text-white md:text-5xl">
                  {getAnalyticsPortfolioHeading(userRole)}
                </h1>
                <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
                  {getAnalyticsPortfolioDescription(userRole)}
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                  Sessions loaded
                </p>
                <p className="mt-2 text-3xl font-semibold text-white">
                  {sessions.length}
                </p>
                <p className="text-sm text-slate-400">Stored review artifacts in scope.</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                  Current filter
                </p>
                <p data-testid="analytics-scope-label" className="mt-2 text-lg font-semibold text-white">
                  {selectedType === 'all' ? 'All session types' : getSessionTypeLabel(selectedType)}
                </p>
                <p className="text-sm text-slate-400">
                  {filteredSessions.length} session{filteredSessions.length === 1 ? '' : 's'} in the current review set.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 rounded-[28px] border border-white/10 bg-white/5 p-5 backdrop-blur lg:grid-cols-[1fr_220px]">
          <label className="space-y-2 text-sm text-slate-300">
            <span className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Session type
            </span>
            <select
              data-testid="analytics-session-type-filter"
              value={selectedType}
              onChange={(event) => setSelectedType(event.target.value)}
              className="w-full rounded-2xl border border-white/10 bg-[#1e2545]/80 px-4 py-3 text-white outline-none ring-0 transition focus:border-[#7b6ef6]/60"
            >
              <option value="all">All types</option>
              <option value="general">General</option>
              <option value="lecture">Lecture</option>
              <option value="practice">Practice</option>
              <option value="discussion">Discussion</option>
            </select>
          </label>

          <div className="flex items-end justify-end">
            <Link
              href="/"
              className="inline-flex w-full items-center justify-center rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/10"
            >
              Back to home
            </Link>
          </div>
        </section>

        {loading ? (
          <section className="rounded-[28px] border border-white/10 bg-white/5 p-8 text-slate-300">
            Loading analytics portfolio…
          </section>
        ) : error ? (
          <section className="rounded-[28px] border border-rose-400/30 bg-rose-500/10 p-8 text-rose-100">
            {error}
          </section>
        ) : sessions.length === 0 ? (
          <section className="rounded-[28px] border border-white/10 bg-white/5 p-10 text-center text-slate-300">
            <p className="text-2xl font-semibold text-white">No sessions recorded yet.</p>
            <p className="mt-3 text-sm text-slate-400">
              Finish a tutoring session, then return here for portfolio review,
              flagged moments, and recommendations.
            </p>
          </section>
        ) : emptyForFilter ? (
          <section className="rounded-[28px] border border-white/10 bg-white/5 p-10 text-center text-slate-300">
            <p className="text-2xl font-semibold text-white">No sessions match this filter.</p>
            <p className="mt-3 text-sm text-slate-400">
              Try widening tutor scope or switching back to all session types.
            </p>
          </section>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <StatCard
                testId="analytics-stat-total-sessions"
                title="Sessions in scope"
                value={String(overview.totalSessions)}
                detail="Current filtered review set."
              />
              <StatCard
                testId="analytics-stat-average-engagement"
                title="Average engagement"
                value={formatScore(overview.averageEngagement)}
                detail="Average engagement score across the selected sessions."
              />
              <StatCard
                testId="analytics-stat-average-student-eye"
                title="Student camera-facing"
                value={formatPercent(overview.averageStudentEye)}
                detail="Average student visual attention signal."
              />
              <StatCard
                testId="analytics-stat-balance-rate"
                title="Balanced talk sessions"
                value={formatPercent(overview.balancedTalkRate)}
                detail="Sessions where tutor talk share stayed inside the session-type target band."
              />
              <StatCard
                testId="analytics-stat-review-count"
                title="Sessions needing review"
                value={String(overview.sessionsNeedingReview)}
                detail={`Average session length ${Math.round(overview.averageDurationMinutes)} min · ${overview.averageInterruptions.toFixed(1)} interruptions on average.`}
              />
            </section>

            <section className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
              <div className="rounded-[28px] border border-white/10 bg-white/5 p-6 backdrop-blur">
                <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Portfolio trend
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold text-white">
                      Track the metric that matters before the next tutoring block.
                    </h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                      {focus.description} The chart below always reflects the same filtered session set as the cards and review queue.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {FOCUS_METRICS.map((metric) => {
                      const active = metric.key === focusMetric
                      return (
                        <button
                          key={metric.key}
                          data-testid={`analytics-focus-${metric.key}`}
                          onClick={() => setFocusMetric(metric.key)}
                          className={`rounded-full border px-3 py-1.5 text-sm transition ${
                            active
                              ? 'border-white/20 bg-white text-slate-950'
                              : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                          }`}
                        >
                          {metric.label}
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div data-testid="analytics-trend-chart" className="mt-6 h-[320px] rounded-3xl border border-white/10 bg-slate-950/50 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 12, right: 16, left: 0, bottom: 8 }}>
                      <CartesianGrid stroke="rgba(148,163,184,0.15)" vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fill: '#94A3B8', fontSize: 12 }}
                        axisLine={{ stroke: 'rgba(148,163,184,0.18)' }}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: '#94A3B8', fontSize: 12 }}
                        axisLine={{ stroke: 'rgba(148,163,184,0.18)' }}
                        tickLine={false}
                        domain={focusMetric === 'interruptions' ? [0, 'auto'] : [0, 100]}
                      />
                      <Tooltip
                        cursor={{ stroke: 'rgba(255,255,255,0.15)' }}
                        contentStyle={{
                          background: '#020617',
                          border: '1px solid rgba(148,163,184,0.2)',
                          borderRadius: '16px',
                          color: '#E2E8F0',
                        }}
                        formatter={(value: number) => {
                          if (focusMetric === 'interruptions') {
                            return [value, focus.label]
                          }
                          return [`${value.toFixed(0)}${focusMetric === 'engagement' ? '' : '%'}`, focus.label]
                        }}
                        labelFormatter={(value, payload) => {
                          const row = payload?.[0]?.payload as { start_time?: string; session_id?: string } | undefined
                          return row?.start_time
                            ? `${new Date(row.start_time).toLocaleDateString()} · ${row.session_id?.slice(0, 8) ?? ''}`
                            : String(value)
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey={focusMetric}
                        stroke={focus.color}
                        strokeWidth={3}
                        dot={{ r: 4, fill: focus.color, strokeWidth: 0 }}
                        activeDot={{ r: 6 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <TrendBadge label="Engagement" trend={trendSnapshot.engagement} />
                  <TrendBadge label="Student camera-facing" trend={trendSnapshot.studentEye} />
                  <TrendBadge label="Interruptions" trend={trendSnapshot.interruptions} />
                  <TrendBadge label="Talk balance" trend={trendSnapshot.talkBalance} />
                </div>
              </div>

              <div
                data-testid="analytics-action-queue"
                className="rounded-[28px] border border-white/10 bg-white/5 p-6 backdrop-blur"
              >
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Review queue
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-white">
                    What deserves a tutor or admin follow-up first?
                  </h2>
                </div>
                {actionQueue.length === 0 ? (
                  <div className="mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-400/10 p-5 text-sm text-emerald-100">
                    No urgent review items in the current scope. The stored sessions are within expected coaching bounds.
                  </div>
                ) : (
                  <div className="mt-6 space-y-3">
                    {actionQueue.map((item) => (
                      <Link
                        key={item.sessionId}
                        href={`/analytics/${item.sessionId}`}
                        className={`block rounded-3xl border p-4 transition hover:-translate-y-0.5 hover:bg-white/10 ${toneClasses(item.tone)}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold">{item.title}</p>
                            <p className="mt-2 text-sm opacity-90">{item.description}</p>
                          </div>
                          <span className="rounded-full border border-current/20 px-2 py-1 text-xs uppercase tracking-[0.18em]">
                            P{Math.min(item.severity, 4)}
                          </span>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </section>

            <section>
              <div className="mb-4 flex items-end justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Session cards
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-white">
                    Drill into any session without losing the coaching context.
                  </h2>
                </div>
                <p className="text-sm text-slate-400">
                  Sorted by most recent session first.
                </p>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                {filteredSessions.map((session) => {
                  const health = getSessionHealth(session)
                  return (
                    <div
                      key={session.session_id}
                      data-testid={`analytics-session-card-${session.session_id}`}
                      className="group rounded-[28px] border border-white/10 bg-white/5 p-5 transition hover:-translate-y-1 hover:border-sky-300/30 hover:bg-white/10"
                    >
                      <div className="flex flex-col gap-4">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] ${toneClasses(health.tone)}`}>
                                {health.label}
                              </span>
                              <span className="rounded-full border border-white/10 bg-slate-950/50 px-3 py-1 text-xs text-slate-300">
                                {getSessionTypeLabel(session.session_type)}
                              </span>
                            </div>
                            <h3 className="mt-3 text-xl font-semibold text-white">
                              {getSessionDisplayTitle(session)}
                            </h3>
                            <p className="mt-1 text-sm text-slate-400">
                              {new Date(session.start_time).toLocaleString()} · {formatMinutes(session.duration_seconds)}
                            </p>
                          </div>
                          <div className="flex items-start gap-3">
                            <div className="text-right">
                              <p className="text-sm text-slate-400">Engagement</p>
                              <p className="text-3xl font-semibold text-white">
                                {formatScore(session.engagement_score)}
                              </p>
                            </div>
                            <button
                              type="button"
                              data-testid={`analytics-delete-${session.session_id}`}
                              onClick={(e) => openDeleteConfirm(session.session_id, e)}
                              title="Delete session"
                              aria-label={`Delete ${getSessionDisplayTitle(session)}`}
                              className="mt-0.5 rounded-xl border border-white/10 bg-white/5 p-2 text-slate-400 transition hover:border-rose-400/40 hover:bg-rose-500/10 hover:text-rose-300"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                                <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                              </svg>
                            </button>
                          </div>
                        </div>

                        <p className="text-sm leading-6 text-slate-300">
                          {health.summary}
                        </p>

                        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                          <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-3 py-3">
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Student camera-facing
                            </p>
                            <p className="mt-2 text-lg font-semibold text-white">
                              {formatPercent(session.avg_eye_contact.student || 0)}
                            </p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-3 py-3">
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Tutor talk share
                            </p>
                            <p className="mt-2 text-lg font-semibold text-white">
                              {formatPercent(session.talk_time_ratio.tutor || 0)}
                            </p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-3 py-3">
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Interruptions
                            </p>
                            <p className="mt-2 text-lg font-semibold text-white">
                              {session.total_interruptions}
                            </p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-3 py-3">
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Live nudges
                            </p>
                            <p className="mt-2 text-lg font-semibold text-white">
                              {session.nudges_sent}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center justify-between text-sm text-slate-400">
                          <span>
                            {session.flagged_moments.length} flagged moment{session.flagged_moments.length === 1 ? '' : 's'} · {session.degradation_events} degradation event{session.degradation_events === 1 ? '' : 's'}
                          </span>
                          <Link
                            href={`/analytics/${session.session_id}`}
                            className="text-slate-200 transition group-hover:translate-x-1"
                          >
                            Open review →
                          </Link>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          </>
        )}
      </div>
    </main>

    {/* Delete confirmation modal */}
    {deleteConfirm && (
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-dialog-title"
        className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm"
      >
        <div className="w-full max-w-sm rounded-[28px] border border-white/10 bg-slate-900 p-7 shadow-2xl">
          <h2 id="delete-dialog-title" className="text-lg font-semibold text-white">
            Delete this session?
          </h2>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            This will permanently remove the session record and all associated
            analytics. This action cannot be undone.
          </p>
          {deleteError ? (
            <p className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              {deleteError}
            </p>
          ) : null}
          <div className="mt-6 flex gap-3">
            <button
              type="button"
              data-testid="delete-confirm-button"
              disabled={deleting}
              onClick={confirmDelete}
              className="flex-1 rounded-2xl bg-rose-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-rose-500 disabled:opacity-50"
            >
              {deleting ? 'Deleting…' : 'Yes, delete'}
            </button>
            <button
              type="button"
              data-testid="delete-cancel-button"
              disabled={deleting}
              onClick={() => {
                setDeleteError('')
                setDeleteConfirm(null)
              }}
              className="flex-1 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    )}
    </AuthGuard>
  )
}
