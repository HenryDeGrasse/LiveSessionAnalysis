'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceDot,
  ResponsiveContainer,
} from 'recharts'
import { useSession } from 'next-auth/react'
import { apiFetch } from '@/lib/api-client'
import type {
  KeyMoment,
  SessionSummary,
  StudentInsights,
  TranscriptSegment,
} from '@/lib/types'
import {
  ATTENTION_STATES,
  ATTENTION_STATE_COLORS,
  computeAttentionDistributionFallback,
  deriveComparisonDeltas,
  deriveSessionRubric,
  deriveTrendSnapshot,
  formatAttentionState,
  formatClock,
  formatDelta,
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
  getAnalyticsDetailTitle,
  isStudentAnalyticsView,
} from '@/lib/analytics-view'
import { DonutChart, NudgeHistoryItem } from '@/components/charts'
import type { DonutSegment } from '@/components/charts'
import { AuthGuard } from '@/components/auth/AuthGuard'

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
  { key: 'studentEnergy', label: 'Student speaking energy', color: '#F59E0B' },
  { key: 'tutorTalk', label: 'Tutor talk share', color: '#38BDF8' },
  { key: 'studentTalk', label: 'Student talk share', color: '#F43F5E' },
]

function getEngagementFeedback(engagementPercent: number): string {
  if (engagementPercent >= 80) return "You were highly focused — excellent work!"
  if (engagementPercent >= 65) return "Good focus overall. A few more active moments could push it even higher."
  if (engagementPercent >= 50) return "Decent effort. Try to minimise distractions to improve further."
  if (engagementPercent >= 35) return "There's room to grow — small habits like staying in frame help a lot."
  return "Sessions with lower engagement can be improved by reducing distractions and staying present."
}

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

function renderFlaggedDotShape(
  dotColor: string,
  description: string,
  shapeProps: { cx?: number; cy?: number }
) {
  const x = shapeProps.cx ?? 0
  const y = shapeProps.cy ?? 0
  return (
    <g style={{ cursor: 'pointer' }}>
      <circle cx={x} cy={y} r={6} fill={dotColor} stroke="#020617" strokeWidth={2} />
      <text x={x} y={y - 14} textAnchor="middle" fill={dotColor} fontSize={14}>
        ⚑
      </text>
      <title>{description}</title>
    </g>
  )
}

function renderKeyMomentDotShape(
  dotColor: string,
  description: string,
  shapeProps: { cx?: number; cy?: number },
  onClick: () => void
) {
  const x = shapeProps.cx ?? 0
  const y = shapeProps.cy ?? 0
  return (
    <g
      style={{ cursor: 'pointer' }}
      onClick={onClick}
      role="button"
      aria-label={`Jump to key moment: ${description}`}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick()
        }
      }}
    >
      <circle cx={x} cy={y} r={7} fill={dotColor} stroke="#020617" strokeWidth={2} />
      <text x={x} y={y - 15} textAnchor="middle" fill={dotColor} fontSize={14}>
        ◆
      </text>
      <title>{description}</title>
    </g>
  )
}

function parseClockLabelToSeconds(value: string): number | null {
  if (!value) return null
  const parts = value.split(':').map((part) => Number(part.trim()))
  if (parts.some((part) => Number.isNaN(part) || part < 0)) return null
  if (parts.length === 2) {
    return parts[0] * 60 + parts[1]
  }
  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2]
  }
  return null
}

function formatTranscriptTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const wholeSeconds = Math.round(seconds)
  const minutes = Math.floor(wholeSeconds / 60)
  const remainingSeconds = wholeSeconds % 60
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

function DetailStat({
  label,
  value,
  detail,
  tooltip,
  testId,
}: {
  label: string
  value: string
  detail: string
  tooltip?: string
  testId?: string
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-3xl border border-white/10 bg-white/5 p-5"
    >
      <p className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-400">
        <span>{label}</span>
        {tooltip ? (
          <span
            className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-white/15 text-[10px] font-semibold normal-case text-slate-300"
            title={tooltip}
            aria-label={tooltip}
            tabIndex={0}
          >
            i
          </span>
        ) : null}
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
    <div className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4">
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
  const { data: authSession, status: authStatus } = useSession()
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [recommendations, setRecommendations] = useState<string[]>([])
  const [studentInsights, setStudentInsights] = useState<StudentInsights | null>(null)
  const [peerSessions, setPeerSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [titleSaving, setTitleSaving] = useState(false)
  const [titleError, setTitleError] = useState('')
  const [seriesVisible, setSeriesVisible] = useState<DetailSeriesKey[]>([
    'engagement',
    'studentEye',
    'studentEnergy',
  ])
  const [activeTab, setActiveTab] = useState<'overview' | 'transcript'>('overview')
  const [transcriptQuery, setTranscriptQuery] = useState('')
  const [selectedKeyMomentIndex, setSelectedKeyMomentIndex] = useState<number | null>(null)
  const transcriptMomentRefs = useRef<Record<number, HTMLDivElement | null>>({})

  const accessToken = authSession?.user?.accessToken
  const isStudentView = isStudentAnalyticsView(authSession?.user?.role)

  const saveSessionTitle = async () => {
    if (!session || !titleDraft.trim() || titleSaving) return

    setTitleSaving(true)
    setTitleError('')
    try {
      const response = await apiFetch(`/api/analytics/sessions/${session.session_id}`, {
        method: 'PATCH',
        accessToken,
        body: JSON.stringify({ session_title: titleDraft.trim() }),
      })
      if (!response.ok) {
        throw new Error('Failed to update session title')
      }
      const updated = (await response.json()) as SessionSummary
      setSession(updated)
      setTitleDraft(updated.session_title || '')
      setEditingTitle(false)
    } catch (error) {
      setTitleError(error instanceof Error ? error.message : 'Failed to update session title')
    } finally {
      setTitleSaving(false)
    }
  }

  useEffect(() => {
    // Only fetch when the user is fully authenticated. Guarding against
    // 'loading' alone is insufficient — 'unauthenticated' users must also be
    // blocked because the backend serves detail and recommendation requests
    // without auth in backward-compat mode (200 OK), which would expose
    // session data before the AuthGuard redirect fires.
    if (authStatus !== 'authenticated') return

    let cancelled = false

    Promise.all([
      apiFetch(`/api/analytics/sessions/${sessionId}`, { accessToken }).then(async (response) => {
        if (!response.ok) return null
        const data = await response.json()
        // Strip tutor-only coaching payload for student viewers so that
        // nudge details are never exposed in the browser even if the backend
        // returns them (defensive measure while backend role-filtering matures).
        if (isStudentView && data) {
          data.nudge_details = []
        }
        return data
      }),
      // Students should not receive the recommendations endpoint response —
      // recommendations are coaching-specific, tutor-only content.
      isStudentView
        ? Promise.resolve([])
        : apiFetch(`/api/analytics/sessions/${sessionId}/recommendations`, { accessToken }).then(
            async (response) => {
              if (!response.ok) return []
              return response.json()
            }
          ),
      // Students receive a dedicated insights payload; tutors do not.
      isStudentView
        ? apiFetch(`/api/analytics/sessions/${sessionId}/student-insights`, { accessToken }).then(
            async (response) => {
              if (!response.ok) return null
              return response.json()
            }
          )
        : Promise.resolve(null),
    ])
      .then(([sessionData, recs, insights]) => {
        if (cancelled) return
        setSession(sessionData)
        setTitleDraft(sessionData?.session_title || '')
        setRecommendations(Array.isArray(recs) ? recs : [])
        setStudentInsights(insights ?? null)
      })
      .catch(() => {
        if (!cancelled) {
          setSession(null)
          setRecommendations([])
          setStudentInsights(null)
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
  }, [sessionId, authStatus, accessToken, isStudentView])

  useEffect(() => {
    if (!session) {
      setPeerSessions([])
      return
    }

    // Same guard: require full authentication, not just non-loading.
    if (authStatus !== 'authenticated') return

    let cancelled = false
    const params = new URLSearchParams({ last_n: '8' })
    if (session.tutor_id) {
      params.set('tutor_id', session.tutor_id)
    }

    apiFetch(`/api/analytics/sessions?${params.toString()}`, { accessToken })
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, authStatus, accessToken])

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

  const talkDonutSegments = useMemo((): DonutSegment[] => {
    if (!session) return []
    const tutorPct = Math.round((session.talk_time_ratio.tutor || 0) * 100)
    const studentPct = Math.max(0, 100 - tutorPct)
    return [
      { label: 'Tutor', value: tutorPct, color: '#38BDF8' },
      { label: 'Student', value: studentPct, color: '#34D399' },
    ]
  }, [session])

  const attentionDistribution = useMemo(() => {
    if (!session) return null
    return computeAttentionDistributionFallback(session)
  }, [session])

  const attentionDonutSegments = useMemo((): DonutSegment[] => {
    if (!attentionDistribution) return []
    return ATTENTION_STATES.filter(
      (state) => (attentionDistribution[state] ?? 0) > 0
    ).map((state) => ({
      label: formatAttentionState(state),
      value: Math.round((attentionDistribution[state] ?? 0) * 100),
      color: ATTENTION_STATE_COLORS[state] || '#94A3B8',
    }))
  }, [attentionDistribution])

  const flaggedDots = useMemo(() => {
    if (!session || timelineData.length === 0) return []
    const duration = session.duration_seconds
    if (duration <= 0) return []

    return session.flagged_moments.map((moment) => {
      const idx = Math.min(
        Math.round((moment.timestamp / duration) * timelineData.length),
        timelineData.length - 1
      )
      const clampedIdx = Math.max(0, idx)
      const yValue = timelineData[clampedIdx]?.engagement ?? 50
      return {
        ...moment,
        timelineIndex: clampedIdx,
        timelineLabel: timelineData[clampedIdx]?.label ?? `#${clampedIdx + 1}`,
        yValue,
        dotColor: moment.direction === 'below' ? '#F43F5E' : '#F59E0B',
      }
    })
  }, [session, timelineData])

  const transcriptAvailable = session?.transcript_available ?? (session?.transcript_word_count ?? 0) > 0

  const transcriptSegments = useMemo(() => {
    if (!session?.transcript_segments) return []
    return session.transcript_segments.filter((segment) => segment.text?.trim())
  }, [session])

  const filteredTranscriptSegments = useMemo(() => {
    const query = transcriptQuery.trim().toLowerCase()
    if (!query) return transcriptSegments
    return transcriptSegments.filter((segment) => {
      const haystack = [segment.role, segment.text, formatTranscriptTimestamp(segment.start_time)]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [transcriptQuery, transcriptSegments])

  const keyMomentDots = useMemo(() => {
    if (!session || timelineData.length === 0 || (session.key_moments?.length ?? 0) === 0) {
      return []
    }

    const duration = session.duration_seconds
    const totalPoints = timelineData.length
    return session.key_moments!.map((moment, index) => {
      const seconds = parseClockLabelToSeconds(moment.time)
      if (seconds == null || duration <= 0) {
        return {
          ...moment,
          timelineIndex: Math.min(index, totalPoints - 1),
          timelineLabel: timelineData[Math.min(index, totalPoints - 1)]?.label ?? `#${index + 1}`,
          yValue: timelineData[Math.min(index, totalPoints - 1)]?.engagement ?? 50,
        }
      }

      const idx = Math.max(
        0,
        Math.min(Math.round((seconds / duration) * totalPoints), totalPoints - 1)
      )
      return {
        ...moment,
        timelineIndex: idx,
        timelineLabel: timelineData[idx]?.label ?? `#${idx + 1}`,
        yValue: timelineData[idx]?.engagement ?? 50,
      }
    })
  }, [session, timelineData])

  useEffect(() => {
    setTranscriptQuery('')
    setSelectedKeyMomentIndex(null)
    setActiveTab('overview')
  }, [sessionId])

  const jumpToKeyMoment = (index: number) => {
    setSelectedKeyMomentIndex(index)
    setActiveTab('transcript')
    window.requestAnimationFrame(() => {
      transcriptMomentRefs.current[index]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    })
  }

  const toggleSeries = (seriesKey: DetailSeriesKey) => {
    setSeriesVisible((current) => {
      if (current.includes(seriesKey)) {
        if (current.length === 1) return current
        return current.filter((value) => value !== seriesKey)
      }
      return [...current, seriesKey]
    })
  }

  // AuthGuard must be the outermost wrapper — including the loading and
  // not-found states — so unauthenticated users always get redirected to
  // /login instead of being stuck on a loading or blank screen.
  if (loading) {
    return (
      <AuthGuard>
        <main className="min-h-screen bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] px-6 pb-10 pt-20 text-slate-300">
          Loading session review…
        </main>
      </AuthGuard>
    )
  }

  if (!session || !sessionHealth) {
    return (
      <AuthGuard>
        <main className="min-h-screen bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] px-6 pb-10 pt-20 text-slate-300">
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
      </AuthGuard>
    )
  }

  return (
    <AuthGuard>
    <main className="min-h-screen bg-gradient-to-b from-[#1a1f3a] to-[#252b4a] text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 pb-10 pt-20 lg:px-8">
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
              <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  {editingTitle ? (
                    <div className="space-y-2">
                      <input
                        value={titleDraft}
                        onChange={(event) => setTitleDraft(event.target.value)}
                        className="w-full rounded-2xl border border-white/10 bg-[#1e2545]/80 px-4 py-3 text-2xl font-semibold tracking-tight text-white outline-none focus:border-[#7b6ef6]/60 md:text-3xl"
                        maxLength={120}
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void saveSessionTitle()}
                          disabled={titleSaving || !titleDraft.trim()}
                          className="rounded-full border border-sky-400/40 bg-sky-500/15 px-3 py-1 text-xs font-medium text-sky-100 disabled:opacity-50"
                        >
                          {titleSaving ? 'Saving…' : 'Save title'}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingTitle(false)
                            setTitleDraft(session.session_title || '')
                            setTitleError('')
                          }}
                          className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200"
                        >
                          Cancel
                        </button>
                        {titleError ? <span className="text-xs text-rose-300">{titleError}</span> : null}
                      </div>
                    </div>
                  ) : (
                    <>
                      <h1
                        data-testid="analytics-detail-title"
                        className="text-4xl font-semibold tracking-tight text-white md:text-5xl"
                      >
                        {getAnalyticsDetailTitle(authSession?.user?.role, session)}
                      </h1>
                      {!isStudentView && (
                        <button
                          type="button"
                          onClick={() => {
                            setEditingTitle(true)
                            setTitleDraft(getSessionDisplayTitle(session))
                            setTitleError('')
                          }}
                          className="mt-3 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200 transition hover:bg-white/10"
                        >
                          Rename session
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
              <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
                {sessionHealth.summary} This review keeps the live-call UI clean,
                then concentrates the richer coaching readout here.
              </p>
              <div className="mt-5 flex flex-wrap gap-4 text-sm text-slate-400">
                <span>Started {new Date(session.start_time).toLocaleString()}</span>
                <span>Duration {formatMinutes(session.duration_seconds)}</span>
                <button
                  type="button"
                  className="group cursor-pointer text-slate-500 transition-colors hover:text-slate-300"
                  title={`Click to copy: ${session.session_id}`}
                  onClick={() => {
                    navigator.clipboard.writeText(session.session_id)
                  }}
                >
                  Ref: {session.session_id.slice(0, 8)}…
                  <span className="ml-1 text-[10px] opacity-0 transition-opacity group-hover:opacity-100">
                    copy
                  </span>
                </button>
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

        {/* Tab switcher — only visible when transcript data exists */}
        {transcriptAvailable && (
          <section data-testid="analytics-tab-bar" className="flex gap-2">
            <button
              type="button"
              data-testid="analytics-tab-overview"
              onClick={() => setActiveTab('overview')}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                activeTab === 'overview'
                  ? 'border-[#7b6ef6]/50 bg-[#7b6ef6]/20 text-white'
                  : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
              }`}
            >
              Overview
            </button>
            <button
              type="button"
              data-testid="analytics-tab-transcript"
              onClick={() => setActiveTab('transcript')}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                activeTab === 'transcript'
                  ? 'border-[#7b6ef6]/50 bg-[#7b6ef6]/20 text-white'
                  : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
              }`}
            >
              Transcript
            </button>
          </section>
        )}

        {/* --- Transcript Tab --- */}
        {activeTab === 'transcript' && transcriptAvailable && session && (
          <>
            {session.ai_summary && (
              <section
                data-testid="analytics-ai-summary"
                className="rounded-[28px] border border-violet-400/20 bg-[radial-gradient(circle_at_top_left,_rgba(139,92,246,0.12),_transparent_60%)] bg-[#1e2545]/80 p-6"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-violet-400">
                  AI Session Summary
                </p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  Natural language recap
                </h2>
                <p
                  data-testid="analytics-ai-summary-text"
                  className="mt-4 text-base leading-7 text-slate-200"
                >
                  {session.ai_summary}
                </p>
                {session.transcript_word_count != null && (
                  <p className="mt-3 text-sm text-slate-400">
                    Based on {session.transcript_word_count.toLocaleString()} words of transcript.
                  </p>
                )}
              </section>
            )}

            {(session.topics_covered?.length ?? 0) > 0 && (
              <section
                data-testid="analytics-topics-covered"
                className="rounded-[28px] border border-white/10 bg-white/5 p-6"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Topics Covered
                </p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  Understanding levels by topic
                </h2>
                <div className="mt-6 grid gap-4">
                  {session.topics_covered!.map((topic) => {
                    const understanding = session.student_understanding_map?.[topic]
                    const pct = understanding != null ? Math.round(understanding * 100) : null
                    const tone = pct == null ? 'slate' : pct >= 70 ? 'emerald' : pct >= 45 ? 'amber' : 'rose'
                    return (
                      <div
                        key={topic}
                        data-testid={`analytics-topic-${topic}`}
                        className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-white">{topic}</p>
                          {pct != null ? (
                            <span className={`rounded-full border px-3 py-1 text-sm ${toneClasses(tone as 'emerald' | 'amber' | 'rose' | 'slate' | 'violet')}`}>
                              {pct}%
                            </span>
                          ) : (
                            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-sm text-slate-400">
                              —
                            </span>
                          )}
                        </div>
                        {pct != null && (
                          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                            <div
                              className={`h-full rounded-full ${
                                tone === 'emerald'
                                  ? 'bg-emerald-400'
                                  : tone === 'amber'
                                    ? 'bg-amber-400'
                                    : 'bg-rose-400'
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            )}

            <section
              data-testid="analytics-full-transcript"
              className="rounded-[28px] border border-white/10 bg-white/5 p-6"
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Full Transcript
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-white">
                    Search and review the full session transcript
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    Scroll through the finalized utterances or filter by speaker, phrase, or timestamp.
                  </p>
                </div>
                <label className="block">
                  <span className="sr-only">Search transcript</span>
                  <input
                    data-testid="analytics-transcript-search"
                    type="search"
                    value={transcriptQuery}
                    onChange={(event) => setTranscriptQuery(event.target.value)}
                    placeholder="Search transcript…"
                    className="w-full min-w-[260px] rounded-2xl border border-white/10 bg-[#1e2545]/80 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-violet-400/40 lg:w-[320px]"
                  />
                </label>
              </div>

              {transcriptSegments.length > 0 ? (
                <div
                  data-testid="analytics-transcript-scroll"
                  className="mt-6 max-h-[420px] space-y-3 overflow-y-auto pr-2"
                >
                  {filteredTranscriptSegments.length > 0 ? (
                    filteredTranscriptSegments.map((segment: TranscriptSegment, index) => {
                      const segmentTime = formatTranscriptTimestamp(segment.start_time)
                      const isHighlighted = selectedKeyMomentIndex != null && session.key_moments?.[selectedKeyMomentIndex]?.time === segmentTime
                      return (
                        <div
                          key={segment.utterance_id || `${segment.role}-${segment.start_time}-${index}`}
                          data-testid={`analytics-transcript-segment-${index}`}
                          className={`rounded-3xl border p-4 transition ${
                            isHighlighted
                              ? 'border-violet-400/35 bg-violet-400/10'
                              : 'border-white/10 bg-[#1e2545]/60'
                          }`}
                        >
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-center gap-2">
                              <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] ${toneClasses(segment.role === 'tutor' ? 'violet' : 'emerald')}`}>
                                {segment.role}
                              </span>
                              <span className="text-xs font-medium tabular-nums text-slate-400">
                                {segmentTime}
                              </span>
                            </div>
                            {segment.confidence != null && segment.confidence > 0 && (
                              <span className="text-xs text-slate-500">
                                Confidence {Math.round(segment.confidence * 100)}%
                              </span>
                            )}
                          </div>
                          <p className="mt-3 text-sm leading-6 text-slate-200">{segment.text}</p>
                        </div>
                      )
                    })
                  ) : (
                    <div
                      data-testid="analytics-transcript-no-results"
                      className="rounded-3xl border border-dashed border-white/10 bg-[#1e2545]/40 p-6 text-sm text-slate-300"
                    >
                      No transcript lines matched “{transcriptQuery.trim()}”.
                    </div>
                  )}
                </div>
              ) : (
                <div className="mt-6 rounded-3xl border border-dashed border-white/10 bg-[#1e2545]/40 p-6 text-sm text-slate-300">
                  Transcript storage is enabled, but the finalized utterance list is not available yet.
                </div>
              )}
            </section>

            {(session.key_moments?.length ?? 0) > 0 && (
              <section
                data-testid="analytics-key-moments"
                className="rounded-[28px] border border-white/10 bg-white/5 p-6"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Key Moments
                </p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  Notable events from the session
                </h2>
                <div className="mt-6 space-y-4">
                  {session.key_moments!.map((moment: KeyMoment, idx: number) => (
                    <div
                      key={`key-moment-${idx}`}
                      ref={(element) => {
                        transcriptMomentRefs.current[idx] = element
                      }}
                      data-testid={`analytics-key-moment-${idx}`}
                      className={`rounded-3xl border p-4 transition ${
                        selectedKeyMomentIndex === idx
                          ? 'border-sky-400/35 bg-sky-400/10'
                          : 'border-white/10 bg-[#1e2545]/60'
                      }`}
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-white">
                            {moment.description}
                          </p>
                          {moment.significance && (
                            <p className="mt-1 text-sm text-slate-400">
                              {moment.significance}
                            </p>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => jumpToKeyMoment(idx)}
                          className="rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-sky-100 transition hover:bg-sky-400/20"
                        >
                          {moment.time}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!isStudentView && (session.follow_up_recommendations?.length ?? 0) > 0 && (
              <section
                data-testid="analytics-follow-up-recommendations"
                className="rounded-[28px] border border-white/10 bg-white/5 p-6"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Follow-up Recommendations
                </p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  Suggested next steps for upcoming sessions
                </h2>
                <div className="mt-6 space-y-3">
                  {session.follow_up_recommendations!.map((rec, idx) => (
                    <div
                      key={`follow-up-${idx}`}
                      className="rounded-3xl border border-violet-400/20 bg-violet-400/10 p-4"
                    >
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 rounded-full border border-violet-300/30 px-2 py-1 text-xs uppercase tracking-[0.18em] text-violet-100">
                          {idx + 1}
                        </span>
                        <p className="text-sm leading-6 text-violet-50">{rec}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!session.ai_summary && transcriptSegments.length === 0 && (
              <section
                data-testid="analytics-transcript-placeholder"
                className="rounded-[28px] border border-white/10 bg-white/5 p-6"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Transcript
                </p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  Transcript recorded
                </h2>
                <p className="mt-4 text-base leading-7 text-slate-300">
                  This session recorded {(session.transcript_word_count ?? 0).toLocaleString()} words of transcript.
                  AI summary and transcript enrichment are still being prepared.
                </p>
              </section>
            )}
          </>
        )}

        {/* --- Overview Tab (default) --- */}
        {activeTab === 'overview' && (
        <>
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
            label="Student speaking energy"
            value={formatPercent(session.avg_energy.student || 0)}
            detail="Average student speaking-energy score (while speaking / just after speaking)."
            tooltip="Measured while the student is speaking or has just spoken, so silence does not count as low energy."
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

        {!isStudentView && (
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
                        className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4"
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
              <div className="mt-6 rounded-3xl border border-white/10 bg-[#1e2545]/60 p-5 text-sm leading-6 text-slate-300">
                Not enough peer sessions yet to build a tutor baseline. Once more sessions are stored for the same tutor, this panel will compare engagement, camera-facing, interruptions, and talk share automatically.
              </div>
            )}
          </div>
        </section>
        )}

        {/* Talk time & attention distribution donuts */}
        <section
          data-testid="analytics-detail-donuts"
          className="grid gap-6 md:grid-cols-2"
        >
          {/* Talk-time donut */}
          <div className="rounded-[28px] border border-white/10 bg-white/5 p-6">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Talk time breakdown
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">
              Tutor vs student share
            </h2>
            <div className="mt-6 flex flex-col items-center gap-4">
              <DonutChart
                segments={talkDonutSegments}
                size={180}
                innerLabel={`${Math.round((session.talk_time_ratio.tutor || 0) * 100)}% / ${Math.max(0, 100 - Math.round((session.talk_time_ratio.tutor || 0) * 100))}%`}
                innerSublabel="tutor / student"
              />
              <div className="flex items-center gap-4 text-sm text-slate-300">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-sky-400" />
                  Tutor
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-emerald-400" />
                  Student
                </span>
              </div>
              {session.turn_counts &&
                ((session.turn_counts.tutor ?? 0) > 0 ||
                  (session.turn_counts.student ?? 0) > 0) && (
                <p className="text-sm text-slate-400">
                  Tutor: {session.turn_counts.tutor ?? 0} turns · Student: {session.turn_counts.student ?? 0} turns
                </p>
              )}
            </div>
          </div>

          {/* Attention state distribution donut */}
          <div className="rounded-[28px] border border-white/10 bg-white/5 p-6">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Student attention breakdown
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">
              Attention state distribution
            </h2>
            {attentionDonutSegments.length > 0 ? (
              <div className="mt-6 flex flex-col items-center gap-4">
                <DonutChart
                  segments={attentionDonutSegments}
                  size={180}
                />
                <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 text-sm">
                  {attentionDonutSegments.map((segment) => (
                    <span
                      key={segment.label}
                      className="flex items-center gap-1.5 text-slate-300"
                    >
                      <span
                        className="inline-block h-3 w-3 rounded-full"
                        style={{ backgroundColor: segment.color }}
                      />
                      {segment.label} ({segment.value}%)
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mt-6 rounded-3xl border border-white/10 bg-[#1e2545]/60 p-5 text-sm leading-6 text-slate-300">
                Attention distribution is available for sessions recorded after
                the attention-state tracking update. Older sessions show the
                average camera-facing score instead.
              </div>
            )}
          </div>
        </section>

        {/* Student insights — student-only */}
        {isStudentView && studentInsights && (
          <section
            data-testid="analytics-student-insights"
            className="rounded-[28px] border border-violet-400/20 bg-[radial-gradient(circle_at_top_left,_rgba(139,92,246,0.12),_transparent_60%)] bg-[#1e2545]/80 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-violet-400">
                Student view
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Your Session Insights
              </h2>
              <p
                data-testid="analytics-student-insights-summary"
                className="mt-2 text-base leading-7 text-slate-300"
              >
                Your engagement was{' '}
                <span className="font-semibold text-white">
                  {Math.round(studentInsights.engagement_percent)}%
                </span>{' '}
                — {getEngagementFeedback(studentInsights.engagement_percent)}
              </p>
            </div>

            <div className="mt-6 grid gap-4 sm:grid-cols-3">
              <div
                data-testid="analytics-student-insights-engagement"
                className="rounded-3xl border border-violet-400/20 bg-violet-400/10 p-5"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-violet-300">
                  Engagement
                </p>
                <p className="mt-3 text-3xl font-semibold text-white">
                  {Math.round(studentInsights.engagement_percent)}%
                </p>
                <p className="mt-2 text-sm leading-6 text-violet-200/70">
                  Your overall focus and presence score for this session.
                </p>
              </div>

              <div
                data-testid="analytics-student-insights-talk-time"
                className="rounded-3xl border border-sky-400/20 bg-sky-400/10 p-5"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-sky-300">
                  Your talk time
                </p>
                <p className="mt-3 text-3xl font-semibold text-white">
                  {Math.round(studentInsights.talk_time_percent)}%
                </p>
                <p className="mt-2 text-sm leading-6 text-sky-200/70">
                  Share of the session where you were actively speaking.
                </p>
              </div>

              <div
                data-testid="analytics-student-insights-attention"
                className="rounded-3xl border border-emerald-400/20 bg-emerald-400/10 p-5"
              >
                <p className="text-xs uppercase tracking-[0.22em] text-emerald-300">
                  Attention score
                </p>
                <p className="mt-3 text-3xl font-semibold text-white">
                  {Math.round(studentInsights.attention_score)}
                </p>
                <p className="mt-2 text-sm leading-6 text-emerald-200/70">
                  Composite of camera-facing and energy signals (0–100).
                </p>
              </div>
            </div>

            {(studentInsights.tips?.length ?? 0) > 0 && (
              <div className="mt-6">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Tips for next time
                </p>
                <div className="mt-4 space-y-3">
                  {studentInsights.tips.map((tip, tipIdx) => (
                    <div
                      key={`tip-${tipIdx}`}
                      className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4"
                    >
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-violet-400/30 bg-violet-400/10 text-xs font-semibold text-violet-200">
                          {tipIdx + 1}
                        </span>
                        <p className="text-sm leading-6 text-slate-200">{tip}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

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
                Toggle the lines below to focus on attention, energy, or talk-share dynamics over the captured session timeline. Diamond markers indicate AI-detected key moments and jump into the transcript tab when selected.
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
                {flaggedDots.map((dot, dotIdx) => (
                  <ReferenceDot
                    key={`flagged-${dot.metric_name}-${dot.timestamp}-${dotIdx}`}
                    x={dot.timelineLabel}
                    y={dot.yValue}
                    isFront
                    shape={(shapeProps: { cx?: number; cy?: number }) =>
                      renderFlaggedDotShape(dot.dotColor, dot.description, shapeProps)
                    }
                  />
                ))}
                {keyMomentDots.map((moment, momentIdx) => (
                  <ReferenceDot
                    key={`key-moment-${moment.time}-${momentIdx}`}
                    x={moment.timelineLabel}
                    y={moment.yValue}
                    isFront
                    shape={(shapeProps: { cx?: number; cy?: number }) =>
                      renderKeyMomentDotShape(
                        selectedKeyMomentIndex === momentIdx ? '#38BDF8' : '#A78BFA',
                        `${moment.time} · ${moment.description}`,
                        shapeProps,
                        () => jumpToKeyMoment(momentIdx)
                      )
                    }
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        {/* Recommendations (tutor) + Flagged moments (both) */}
        <section className={`grid gap-6 ${!isStudentView ? 'xl:grid-cols-[0.9fr_1.1fr]' : ''}`}>
          {!isStudentView && (
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
          )}

          <div
            data-testid="analytics-detail-flagged-moments"
            className="rounded-[28px] border border-white/10 bg-white/5 p-6"
          >
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Flagged moments
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                {isStudentView ? 'Engagement dips during session' : 'The exact moments worth revisiting.'}
              </h2>
            </div>
            {session.flagged_moments.length > 0 ? (
              <div className="mt-6 space-y-4">
                {session.flagged_moments.map((moment, index) => (
                  <div
                    key={`${moment.metric_name}-${moment.timestamp}-${index}`}
                    className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4"
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
              <div className="mt-6 rounded-3xl border border-white/10 bg-[#1e2545]/60 p-5 text-sm leading-6 text-slate-300">
                No flagged moments crossed the saved thresholds for this session.
              </div>
            )}
          </div>
        </section>

        {/* Nudge history — tutor-only */}
        {!isStudentView && (
        <section
          data-testid="analytics-detail-nudge-history"
          className="rounded-[28px] border border-white/10 bg-white/5 p-6"
        >
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Coaching nudges sent during session
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">
              Nudge history
            </h2>
          </div>
          {session.nudge_details && session.nudge_details.length > 0 ? (
            <div className="mt-6 space-y-3">
              {session.nudge_details.map((nudge, nudgeIdx) => (
                <NudgeHistoryItem
                  key={`${nudge.nudge_type}-${nudge.timestamp}-${nudgeIdx}`}
                  nudge={nudge}
                />
              ))}
            </div>
          ) : session.nudges_sent > 0 ? (
            <div className="mt-6 rounded-3xl border border-white/10 bg-[#1e2545]/60 p-5 text-sm leading-6 text-slate-300">
              {session.nudges_sent} nudge{session.nudges_sent === 1 ? ' was' : 's were'} sent during this session. Detailed nudge history is available for newer sessions.
            </div>
          ) : (
            <div className="mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-400/10 p-5 text-sm leading-6 text-emerald-100">
              No coaching nudges were needed during this session.
            </div>
          )}
        </section>
        )}
        </>
        )}

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
            <div className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Tutor</p>
              <p className="mt-2 text-lg font-semibold text-white">{session.tutor_id || 'Not set'}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Session type</p>
              <p className="mt-2 text-lg font-semibold text-white">{getSessionTypeLabel(session.session_type)}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Start time</p>
              <p className="mt-2 text-lg font-semibold text-white">{new Date(session.start_time).toLocaleString()}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-[#1e2545]/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">End time</p>
              <p className="mt-2 text-lg font-semibold text-white">{new Date(session.end_time).toLocaleString()}</p>
            </div>
          </div>
        </section>
      </div>
    </main>
    </AuthGuard>
  )
}
