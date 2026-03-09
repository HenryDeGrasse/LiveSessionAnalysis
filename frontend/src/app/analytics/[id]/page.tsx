'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { API_URL } from '@/lib/constants'
import type { SessionSummary } from '@/lib/types'
import {
  deriveComparisonDeltas,
  deriveSessionRubric,
  deriveTrendSnapshot,
  formatClock,
  formatDelta,
  formatMinutes,
  formatPercent,
  formatScore,
  getSessionHealth,
  getSessionTypeLabel,
  getTrendLabel,
  getTrendTone,
} from '@/lib/analytics'

type DetailSeriesKey =
  | 'engagement'
  | 'studentEye'
  | 'studentEnergy'
  | 'tutorTalk'
  | 'studentTalk'

const DETAIL_SERIES: Array<{
  key: DetailSeriesKey
  label: string
  color: string
}> = [
  { key: 'engagement', label: 'Engagement', color: '#8B5CF6' },
  { key: 'studentEye', label: 'Student camera-facing', color: '#22C55E' },
  { key: 'studentEnergy', label: 'Student energy', color: '#F59E0B' },
  { key: 'tutorTalk', label: 'Tutor talk share', color: '#38BDF8' },
  { key: 'studentTalk', label: 'Student talk share', color: '#F43F5E' },
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

function DetailStat({
  label,
  value,
  detail,
  testId,
}: {
  label: string
  value: string
  detail: string
  testId?: string
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-3xl border border-white/10 bg-white/5 p-5"
    >
      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
        {label}
      </p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{detail}</p>
    </div>
  )
}

function ScoreBar({
  label,
  value,
  hint,
}: {
  label: string
  value: number
  hint: string
}) {
  const tone = value >= 75 ? 'emerald' : value >= 55 ? 'amber' : 'rose'

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{label}</p>
          <p className="mt-1 text-sm leading-6 text-slate-400">{hint}</p>
        </div>
        <div className={`rounded-full border px-3 py-1 text-sm ${toneClasses(tone)}`}>
          {Math.round(value)}
        </div>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${
            tone === 'emerald'
              ? 'bg-emerald-400'
              : tone === 'amber'
              ? 'bg-amber-400'
              : 'bg-rose-400'
          }`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  )
}

export default function SessionDetailPage() {
  const routeParams = useParams<{ id: string }>()
  const sessionId = routeParams.id
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [recommendations, setRecommendations] = useState<string[]>([])
  const [peerSessions, setPeerSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [seriesVisible, setSeriesVisible] = useState<DetailSeriesKey[]>([
    'engagement',
    'studentEye',
    'studentEnergy',
  ])

  useEffect(() => {
    let cancelled = false

    Promise.all([
      fetch(`${API_URL}/api/analytics/sessions/${sessionId}`).then(async (response) => {
        if (!response.ok) return null
        return response.json()
      }),
      fetch(`${API_URL}/api/analytics/sessions/${sessionId}/recommendations`).then(
        async (response) => {
          if (!response.ok) return []
          return response.json()
        }
      ),
    ])
      .then(([sessionData, recs]) => {
        if (cancelled) return
        setSession(sessionData)
        setRecommendations(Array.isArray(recs) ? recs : [])
      })
      .catch(() => {
        if (!cancelled) {
          setSession(null)
          setRecommendations([])
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
  }, [sessionId])

  useEffect(() => {
    if (!session) {
      setPeerSessions([])
      return
    }

    let cancelled = false
    const params = new URLSearchParams({ last_n: '8' })
    if (session.tutor_id) {
      params.set('tutor_id', session.tutor_id)
    }

    fetch(`${API_URL}/api/analytics/sessions?${params.toString()}`)
      .then(async (response) => {
        if (!response.ok) return []
        return response.json()
      })
      .then((data) => {
        if (!cancelled) {
          setPeerSessions(Array.isArray(data) ? data : [])
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPeerSessions([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [session])

  const sessionHealth = useMemo(
    () => (session ? getSessionHealth(session) : null),
    [session]
  )

  const peerBaseline = useMemo(() => {
    if (!session) return []
    return peerSessions.filter((peer) => peer.session_id !== session.session_id)
  }, [peerSessions, session])

  const comparison = useMemo(() => {
    if (!session) return null
    return deriveComparisonDeltas(session, peerBaseline)
  }, [peerBaseline, session])

  const peerTrends = useMemo(
    () => deriveTrendSnapshot(peerSessions),
    [peerSessions]
  )

  const rubric = useMemo(
    () => (session ? deriveSessionRubric(session) : []),
    [session]
  )

  const timelineData = useMemo(() => {
    if (!session) return []

    const timeline = session.timeline || {}
    const maxLength = Math.max(
      timeline.engagement?.length || 0,
      timeline.student_eye_contact?.length || 0,
      timeline.student_energy?.length || 0,
      timeline.tutor_talk_time?.length || 0,
      timeline.student_talk_time?.length || 0
    )

    return Array.from({ length: maxLength }, (_unused, index) => ({
      index,
      label: `#${index + 1}`,
      engagement: timeline.engagement?.[index] ?? 0,
      studentEye: (timeline.student_eye_contact?.[index] ?? 0) * 100,
      studentEnergy: (timeline.student_energy?.[index] ?? 0) * 100,
      tutorTalk: (timeline.tutor_talk_time?.[index] ?? 0) * 100,
      studentTalk: (timeline.student_talk_time?.[index] ?? 0) * 100,
    }))
  }, [session])

  const toggleSeries = (seriesKey: DetailSeriesKey) => {
    setSeriesVisible((current) => {
      if (current.includes(seriesKey)) {
        if (current.length === 1) return current
        return current.filter((value) => value !== seriesKey)
      }
      return [...current, seriesKey]
    })
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-300">
        Loading session review…
      </main>
    )
  }

  if (!session || !sessionHealth) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-300">
        <div className="mx-auto max-w-4xl rounded-[28px] border border-white/10 bg-white/5 p-8">
          <p className="text-2xl font-semibold text-white">
            Session not found or not yet available.
          </p>
          <Link
            href="/analytics"
            className="mt-4 inline-flex rounded-full border border-white/10 px-4 py-2 text-sm text-white transition hover:bg-white/10"
          >
            Back to analytics
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-10 lg:px-8">
        <section
          data-testid="analytics-detail-page"
          className="relative overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(139,92,246,0.2),_transparent_30%),radial-gradient(circle_at_top_right,_rgba(34,197,94,0.15),_transparent_28%),linear-gradient(180deg,_rgba(15,23,42,0.96),_rgba(2,6,23,0.98))] p-8 shadow-[0_28px_120px_rgba(2,6,23,0.55)]"
        >
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] ${toneClasses(sessionHealth.tone)}`}>
                  {sessionHealth.label}
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.2em] text-slate-300">
                  {getSessionTypeLabel(session.session_type)}
                </span>
              </div>
              <h1
                data-testid="analytics-detail-title"
                className="mt-4 text-4xl font-semibold tracking-tight text-white md:text-5xl"
              >
                {session.tutor_id || 'Unassigned tutor'} · session review
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
                {sessionHealth.summary} This review keeps the live-call UI clean,
                then concentrates the richer coaching readout here.
              </p>
              <div className="mt-5 flex flex-wrap gap-4 text-sm text-slate-400">
                <span>Started {new Date(session.start_time).toLocaleString()}</span>
                <span>Duration {formatMinutes(session.duration_seconds)}</span>
                <span>Session ID {session.session_id}</span>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Engagement
                </p>
                <p className="mt-3 text-4xl font-semibold text-white">
                  {formatScore(session.engagement_score)}
                </p>
                <p className="mt-2 text-sm text-slate-400">
                  Average engagement score across the saved timeline.
                </p>
              </div>
              <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Derived review score
                </p>
                <p data-testid="analytics-detail-health-score" className="mt-3 text-4xl font-semibold text-white">
                  {Math.round(sessionHealth.score)}
                </p>
                <p className="mt-2 text-sm text-slate-400">
                  Frontend-derived synthesis from engagement, talk balance,
                  interruptions, and coaching load.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
          <DetailStat
            testId="analytics-detail-duration"
            label="Duration"
            value={formatMinutes(session.duration_seconds)}
            detail="Time between the first and last stored analytics snapshot."
          />
          <DetailStat
            label="Student camera-facing"
            value={formatPercent(session.avg_eye_contact.student || 0)}
            detail="Average student visual attention / camera-facing signal."
          />
          <DetailStat
            label="Student energy"
            value={formatPercent(session.avg_energy.student || 0)}
            detail="Average student audio-primary energy score."
          />
          <DetailStat
            label="Tutor talk share"
            value={formatPercent(session.talk_time_ratio.tutor || 0)}
            detail="Compared against the target band for this session type."
          />
          <DetailStat
            label="Interruptions"
            value={String(session.total_interruptions)}
            detail="Cumulative interruption count saved in the summary."
          />
          <DetailStat
            label="Live coach load"
            value={String(session.nudges_sent)}
            detail={`${session.flagged_moments.length} flagged moments · ${session.degradation_events} degradation event${session.degradation_events === 1 ? '' : 's'}.`}
          />
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <div
            data-testid="analytics-detail-rubric"
            className="rounded-[28px] border border-white/10 bg-white/5 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Derived coaching lenses
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                A concise rubric for tutor/admin follow-up.
              </h2>
            </div>
            <div className="mt-6 grid gap-4">
              {rubric.map((item) => (
                <ScoreBar
                  key={item.label}
                  label={item.label}
                  value={item.value}
                  hint={item.hint}
                />
              ))}
            </div>
          </div>

          <div
            data-testid="analytics-detail-comparison-panel"
            className="rounded-[28px] border border-white/10 bg-white/5 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Portfolio comparison
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Compare this session against the recent tutor baseline.
              </h2>
            </div>

            {comparison ? (
              <>
                <p className="mt-3 text-sm leading-6 text-slate-400">
                  Based on {peerBaseline.length} other stored session{peerBaseline.length === 1 ? '' : 's'}{session.tutor_id ? ` for ${session.tutor_id}` : ''}.
                </p>
                <div className="mt-5 grid gap-3">
                  {comparison.map((item) => {
                    const positive = item.goodWhenPositive ? item.delta >= 0 : item.delta <= 0
                    const tone = positive ? 'emerald' : 'rose'
                    return (
                      <div
                        key={item.label}
                        className="rounded-3xl border border-white/10 bg-slate-950/40 p-4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-white">{item.label}</p>
                            <p className="mt-1 text-sm text-slate-400">
                              Current value {item.format === 'percent' ? `${item.value.toFixed(0)}%` : item.format === 'count' ? item.value.toFixed(1) : item.value.toFixed(0)}
                            </p>
                          </div>
                          <span className={`rounded-full border px-3 py-1 text-sm ${toneClasses(tone)}`}>
                            {formatDelta(item.delta, item.format)}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className={`rounded-3xl border p-4 ${toneClasses(getTrendTone(peerTrends.engagement))}`}>
                    <p className="text-xs uppercase tracking-[0.18em] opacity-80">Portfolio engagement</p>
                    <p className="mt-2 text-lg font-semibold">{getTrendLabel(peerTrends.engagement)}</p>
                  </div>
                  <div className={`rounded-3xl border p-4 ${toneClasses(getTrendTone(peerTrends.interruptions))}`}>
                    <p className="text-xs uppercase tracking-[0.18em] opacity-80">Portfolio interruptions</p>
                    <p className="mt-2 text-lg font-semibold">{getTrendLabel(peerTrends.interruptions)}</p>
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/40 p-5 text-sm leading-6 text-slate-300">
                Not enough peer sessions yet to build a tutor baseline. Once more sessions are stored for the same tutor, this panel will compare engagement, camera-facing, interruptions, and talk share automatically.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-white/5 p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Session timeline
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Inspect the saved metric arc, not just the final summary score.
              </h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
                Toggle the lines below to focus on attention, energy, or talk-share dynamics over the captured session timeline.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {DETAIL_SERIES.map((series) => {
                const active = seriesVisible.includes(series.key)
                return (
                  <button
                    key={series.key}
                    data-testid={`analytics-detail-series-${series.key}`}
                    onClick={() => toggleSeries(series.key)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      active
                        ? 'border-white/20 bg-white text-slate-950'
                        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                    }`}
                  >
                    {series.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div
            data-testid="analytics-detail-chart"
            className="mt-6 h-[360px] rounded-3xl border border-white/10 bg-slate-950/50 p-4"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={timelineData} margin={{ top: 12, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="rgba(148,163,184,0.15)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: '#94A3B8', fontSize: 12 }}
                  axisLine={{ stroke: 'rgba(148,163,184,0.18)' }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: '#94A3B8', fontSize: 12 }}
                  axisLine={{ stroke: 'rgba(148,163,184,0.18)' }}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ stroke: 'rgba(255,255,255,0.15)' }}
                  contentStyle={{
                    background: '#020617',
                    border: '1px solid rgba(148,163,184,0.2)',
                    borderRadius: '16px',
                    color: '#E2E8F0',
                  }}
                  formatter={(value: number, name: string) => {
                    return [`${value.toFixed(0)}${name === 'Engagement' ? '' : '%'}`, name]
                  }}
                />
                {DETAIL_SERIES.filter((series) => seriesVisible.includes(series.key)).map((series) => (
                  <Line
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={series.label}
                    stroke={series.color}
                    strokeWidth={series.key === 'engagement' ? 3 : 2.5}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <div
            data-testid="analytics-detail-recommendations"
            className="rounded-[28px] border border-white/10 bg-white/5 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Recommendations
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Concrete next moves for the tutor.
              </h2>
            </div>
            {recommendations.length > 0 ? (
              <div className="mt-6 space-y-3">
                {recommendations.map((recommendation, index) => (
                  <div
                    key={`${recommendation}-${index}`}
                    className="rounded-3xl border border-violet-400/20 bg-violet-400/10 p-4"
                  >
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 rounded-full border border-violet-300/30 px-2 py-1 text-xs uppercase tracking-[0.18em] text-violet-100">
                        {index + 1}
                      </span>
                      <p className="text-sm leading-6 text-violet-50">{recommendation}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-400/10 p-5 text-sm leading-6 text-emerald-100">
                No major post-session recommendations were generated. This session stayed inside the current heuristic thresholds.
              </div>
            )}
          </div>

          <div
            data-testid="analytics-detail-flagged-moments"
            className="rounded-[28px] border border-white/10 bg-white/5 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Flagged moments
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                The exact moments worth revisiting.
              </h2>
            </div>
            {session.flagged_moments.length > 0 ? (
              <div className="mt-6 space-y-4">
                {session.flagged_moments.map((moment, index) => (
                  <div
                    key={`${moment.metric_name}-${moment.timestamp}-${index}`}
                    className="rounded-3xl border border-white/10 bg-slate-950/40 p-4"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-sm font-semibold text-white">
                          {moment.description}
                        </p>
                        <p className="mt-1 text-sm text-slate-400">
                          Metric {moment.metric_name.replace(/_/g, ' ')} moved{' '}
                          {moment.direction === 'above' ? 'above' : 'below'} threshold.
                        </p>
                      </div>
                      <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] ${toneClasses(moment.direction === 'above' ? 'amber' : 'rose')}`}>
                        {formatClock(moment.timestamp)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/40 p-5 text-sm leading-6 text-slate-300">
                No flagged moments crossed the saved thresholds for this session.
              </div>
            )}
          </div>
        </section>

        <section
          data-testid="analytics-detail-metadata"
          className="rounded-[28px] border border-white/10 bg-white/5 p-6"
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Session metadata
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Saved context for downstream admin or QA review.
              </h2>
            </div>
            <Link
              href="/analytics"
              className="inline-flex items-center justify-center rounded-full border border-white/10 px-4 py-2 text-sm text-white transition hover:bg-white/10"
            >
              Back to analytics
            </Link>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Tutor</p>
              <p className="mt-2 text-lg font-semibold text-white">{session.tutor_id || 'Not set'}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Session type</p>
              <p className="mt-2 text-lg font-semibold text-white">{getSessionTypeLabel(session.session_type)}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Start time</p>
              <p className="mt-2 text-lg font-semibold text-white">{new Date(session.start_time).toLocaleString()}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">End time</p>
              <p className="mt-2 text-lg font-semibold text-white">{new Date(session.end_time).toLocaleString()}</p>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
