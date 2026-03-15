import type { AttentionState, SessionSummary } from './types'

export type TrendDirection = 'improving' | 'stable' | 'declining'
export type AnalyticsTone = 'emerald' | 'amber' | 'rose' | 'slate' | 'violet'

export interface DashboardOverview {
  totalSessions: number
  averageEngagement: number
  averageStudentEye: number
  averageInterruptions: number
  balancedTalkRate: number
  sessionsNeedingReview: number
  averageDurationMinutes: number
}

export interface ActionItem {
  sessionId: string
  title: string
  description: string
  severity: number
  tone: AnalyticsTone
}

export interface SessionHealth {
  label: string
  tone: AnalyticsTone
  score: number
  summary: string
}

export interface RubricScore {
  label: string
  value: number
  hint: string
}

export interface ComparisonDelta {
  label: string
  delta: number
  value: number
  format: 'score' | 'percent' | 'count'
  goodWhenPositive: boolean
}

const SESSION_TYPE_LABELS: Record<string, string> = {
  general: 'General',
  lecture: 'Lecture',
  practice: 'Practice',
  discussion: 'Discussion',
}

const TALK_TARGETS: Record<string, number> = {
  general: 0.65,
  lecture: 0.8,
  practice: 0.5,
  discussion: 0.55,
}

const TALK_TOLERANCE: Record<string, number> = {
  general: 0.12,
  lecture: 0.1,
  practice: 0.12,
  discussion: 0.1,
}

export const ATTENTION_STATES: AttentionState[] = [
  'CAMERA_FACING',
  'SCREEN_ENGAGED',
  'DOWN_ENGAGED',
  'OFF_TASK_AWAY',
  'FACE_MISSING',
  'LOW_CONFIDENCE',
]

export const ATTENTION_STATE_LABELS: Record<string, string> = {
  CAMERA_FACING: 'Camera-facing',
  SCREEN_ENGAGED: 'Screen-engaged',
  DOWN_ENGAGED: 'Down-engaged',
  OFF_TASK_AWAY: 'Off-task / away',
  FACE_MISSING: 'Face missing',
  LOW_CONFIDENCE: 'Low confidence',
}

export const ATTENTION_STATE_COLORS: Record<string, string> = {
  CAMERA_FACING: '#10B981',
  SCREEN_ENGAGED: '#0EA5E9',
  DOWN_ENGAGED: '#F59E0B',
  OFF_TASK_AWAY: '#F43F5E',
  FACE_MISSING: '#94A3B8',
  LOW_CONFIDENCE: '#64748B',
}

function clamp(value: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, value))
}

export function average(values: number[]) {
  if (values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

export function getSessionTypeLabel(sessionType: string) {
  return SESSION_TYPE_LABELS[sessionType] || sessionType || 'General'
}

export function getSessionDisplayTitle(session: Pick<SessionSummary, 'session_title' | 'session_type' | 'start_time'>) {
  if (session.session_title && session.session_title.trim().length > 0) {
    return session.session_title.trim()
  }
  return `${getSessionTypeLabel(session.session_type)} · ${new Date(session.start_time).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })}`
}

export function formatPercent(value: number, digits = 0) {
  return `${(value * 100).toFixed(digits)}%`
}

export function formatScore(value: number, digits = 0) {
  return value.toFixed(digits)
}

export function formatMinutes(durationSeconds: number) {
  if (durationSeconds < 60) return `${Math.round(durationSeconds)} sec`
  const minutes = Math.round(durationSeconds / 60)
  return `${minutes} min`
}

function startCase(value: string) {
  return value
    .trim()
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function formatAttentionState(state: string) {
  return ATTENTION_STATE_LABELS[state] || startCase(state) || 'Unknown'
}

export function computeAttentionDistributionFallback(
  session: SessionSummary
): Record<string, number> | null {
  const distribution = session.attention_state_distribution

  if (!distribution || Object.keys(distribution).length === 0) {
    return null
  }

  if (distribution.student && Object.keys(distribution.student).length > 0) {
    return distribution.student
  }

  if (distribution.tutor && Object.keys(distribution.tutor).length > 0) {
    return distribution.tutor
  }

  const firstDistribution = Object.values(distribution).find(
    (entry) => Object.keys(entry).length > 0
  )

  return firstDistribution || null
}

export function formatNudgePriority(priority: string): {
  label: string
  tone: AnalyticsTone
} {
  const normalized = priority.trim().toLowerCase()

  if (normalized === 'high') {
    return { label: 'High priority', tone: 'rose' }
  }

  if (normalized === 'medium') {
    return { label: 'Medium priority', tone: 'amber' }
  }

  if (normalized === 'low') {
    return { label: 'Low priority', tone: 'slate' }
  }

  return {
    label: normalized ? `${startCase(normalized)} priority` : 'Priority',
    tone: 'slate',
  }
}

export function formatClock(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function formatDelta(
  value: number,
  format: ComparisonDelta['format']
) {
  const prefix = value > 0 ? '+' : ''

  if (format === 'percent') {
    return `${prefix}${value.toFixed(0)} pp`
  }

  if (format === 'count') {
    return `${prefix}${value.toFixed(1)}`
  }

  return `${prefix}${value.toFixed(0)}`
}

export function getTrendTone(trend: TrendDirection): AnalyticsTone {
  if (trend === 'improving') return 'emerald'
  if (trend === 'declining') return 'rose'
  return 'slate'
}

export function getTrendLabel(trend: TrendDirection) {
  if (trend === 'improving') return 'Improving'
  if (trend === 'declining') return 'Declining'
  return 'Stable'
}

export function classifyTrend(
  values: number[],
  inverted = false
): TrendDirection {
  if (values.length < 2) return 'stable'

  const n = values.length
  const xMean = (n - 1) / 2
  const yMean = average(values)
  const numerator = values.reduce(
    (sum, value, index) => sum + (index - xMean) * (value - yMean),
    0
  )
  const denominator = values.reduce(
    (sum, _value, index) => sum + (index - xMean) ** 2,
    0
  )

  if (denominator === 0) return 'stable'

  const slope = numerator / denominator
  const valueRange = Math.max(...values) - Math.min(...values) || 1
  const normalizedSlope = valueRange > 0 ? slope / valueRange : 0
  const threshold = 0.1

  if (inverted) {
    if (normalizedSlope < -threshold) return 'improving'
    if (normalizedSlope > threshold) return 'declining'
    return 'stable'
  }

  if (normalizedSlope > threshold) return 'improving'
  if (normalizedSlope < -threshold) return 'declining'
  return 'stable'
}

export function deriveTrendSnapshot(sessions: SessionSummary[]) {
  const chronological = [...sessions].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )

  return {
    engagement: classifyTrend(
      chronological.map((session) => session.engagement_score)
    ),
    studentEye: classifyTrend(
      chronological.map((session) => session.avg_eye_contact.student || 0)
    ),
    interruptions: classifyTrend(
      chronological.map((session) => session.total_interruptions),
      true
    ),
    talkBalance: classifyTrend(
      chronological.map((session) => Math.abs((session.talk_time_ratio.tutor || 0) - getTutorTalkTarget(session.session_type))),
      true
    ),
  }
}

export function getTutorTalkTarget(sessionType: string) {
  return TALK_TARGETS[sessionType] ?? TALK_TARGETS.general
}

export function getTutorTalkTolerance(sessionType: string) {
  return TALK_TOLERANCE[sessionType] ?? TALK_TOLERANCE.general
}

export function isTalkBalanced(session: SessionSummary) {
  const tutorTalk = session.talk_time_ratio.tutor || 0
  const target = getTutorTalkTarget(session.session_type)
  const tolerance = getTutorTalkTolerance(session.session_type)
  return Math.abs(tutorTalk - target) <= tolerance
}

function getSessionPriority(session: SessionSummary) {
  let severity = 0
  const signals: string[] = []

  if (session.engagement_score < 55) {
    severity += 3
    signals.push(`engagement averaged ${formatScore(session.engagement_score)}/100`)
  }

  if ((session.avg_eye_contact.student || 0) < 0.3) {
    severity += 2
    signals.push(`student camera-facing averaged ${formatPercent(session.avg_eye_contact.student || 0)}`)
  }

  if (session.total_interruptions >= 5) {
    severity += 2
    signals.push(`${session.total_interruptions} interruptions were captured`)
  }

  if (!isTalkBalanced(session)) {
    severity += 2
    signals.push(`tutor talk share landed at ${formatPercent(session.talk_time_ratio.tutor || 0)}`)
  }

  if (session.nudges_sent >= 3) {
    severity += 1
    signals.push(`${session.nudges_sent} live nudges were needed`)
  }

  return { severity, signals }
}

export function getSessionHealth(session: SessionSummary): SessionHealth {
  const { severity, signals } = getSessionPriority(session)

  if (severity <= 1 && session.engagement_score >= 75) {
    return {
      label: 'On track',
      tone: 'emerald',
      score: clamp(90 - severity * 8),
      summary:
        'Balanced participation and healthy student presence across the session.',
    }
  }

  if (severity <= 4 && session.engagement_score >= 60) {
    return {
      label: 'Watchlist',
      tone: 'amber',
      score: clamp(72 - severity * 5),
      summary:
        signals[0]
          ? `Worth reviewing because ${signals[0]}.`
          : 'Some coaching signals emerged, but the session stayed workable.',
    }
  }

  return {
    label: 'Needs review',
    tone: 'rose',
    score: clamp(58 - severity * 4),
    summary:
      signals[0]
        ? `Priority review recommended because ${signals[0]}.`
        : 'Several coaching signals stacked up during the session.',
  }
}

export function deriveDashboardOverview(sessions: SessionSummary[]): DashboardOverview {
  const sessionsNeedingReview = sessions.filter(
    (session) => getSessionHealth(session).label !== 'On track'
  ).length

  return {
    totalSessions: sessions.length,
    averageEngagement: average(sessions.map((session) => session.engagement_score)),
    averageStudentEye: average(
      sessions.map((session) => session.avg_eye_contact.student || 0)
    ),
    averageInterruptions: average(
      sessions.map((session) => session.total_interruptions)
    ),
    balancedTalkRate: average(
      sessions.map((session) => (isTalkBalanced(session) ? 1 : 0))
    ),
    sessionsNeedingReview,
    averageDurationMinutes: average(
      sessions.map((session) => session.duration_seconds / 60)
    ),
  }
}

export function deriveActionQueue(sessions: SessionSummary[]): ActionItem[] {
  return sessions
    .map((session) => {
      const { severity, signals } = getSessionPriority(session)
      const health = getSessionHealth(session)
      return {
        sessionId: session.session_id,
        title: getSessionDisplayTitle(session),
        description:
          signals[0]
            ? `${getSessionTypeLabel(session.session_type)} · ${signals[0]}.`
            : 'No urgent coaching follow-up required.',
        severity,
        tone: health.tone,
      }
    })
    .filter((item) => item.severity > 0)
    .sort((a, b) => b.severity - a.severity)
    .slice(0, 4)
}

export function deriveSessionRubric(session: SessionSummary): RubricScore[] {
  const tutorTalk = session.talk_time_ratio.tutor || 0
  const target = getTutorTalkTarget(session.session_type)
  const balanceScore = clamp(100 - (Math.abs(tutorTalk - target) / 0.35) * 100)
  const studentPresenceScore = clamp(
    average([
      (session.avg_eye_contact.student || 0) * 100,
      (session.avg_energy.student || 0) * 100,
    ])
  )
  const frictionScore = clamp(100 - session.total_interruptions * 12)
  const coachingLoadScore = clamp(100 - session.nudges_sent * 18)

  return [
    {
      label: 'Conversation balance',
      value: balanceScore,
      hint: `Tutor talk share ${formatPercent(tutorTalk)} against a ${formatPercent(target)} target for ${getSessionTypeLabel(session.session_type).toLowerCase()}.`,
    },
    {
      label: 'Student presence',
      value: studentPresenceScore,
      hint: `Derived from student camera-facing (${formatPercent(session.avg_eye_contact.student || 0)}) and vocal energy while speaking (${formatPercent(session.avg_energy.student || 0)}), combining pitch variation, loudness, and speech rate via prosody analysis.`,
    },
    {
      label: 'Turn-taking control',
      value: frictionScore,
      hint: `${session.total_interruptions} interruptions were logged in the session history.`,
    },
    {
      label: 'Live coach load',
      value: coachingLoadScore,
      hint: `${session.nudges_sent} nudges were delivered while the session was live.`,
    },
  ]
}

export function deriveComparisonDeltas(
  session: SessionSummary,
  peers: SessionSummary[]
): ComparisonDelta[] | null {
  if (peers.length === 0) return null

  const averageEngagement = average(peers.map((peer) => peer.engagement_score))
  const averageStudentEye = average(
    peers.map((peer) => peer.avg_eye_contact.student || 0)
  )
  const averageInterruptions = average(
    peers.map((peer) => peer.total_interruptions)
  )
  const averageTutorTalk = average(
    peers.map((peer) => peer.talk_time_ratio.tutor || 0)
  )

  return [
    {
      label: 'Engagement vs baseline',
      delta: session.engagement_score - averageEngagement,
      value: session.engagement_score,
      format: 'score',
      goodWhenPositive: true,
    },
    {
      label: 'Student camera-facing',
      delta: (session.avg_eye_contact.student || 0) * 100 - averageStudentEye * 100,
      value: (session.avg_eye_contact.student || 0) * 100,
      format: 'percent',
      goodWhenPositive: true,
    },
    {
      label: 'Interruptions',
      delta: session.total_interruptions - averageInterruptions,
      value: session.total_interruptions,
      format: 'count',
      goodWhenPositive: false,
    },
    {
      label: 'Tutor talk share',
      delta: (session.talk_time_ratio.tutor || 0) * 100 - averageTutorTalk * 100,
      value: (session.talk_time_ratio.tutor || 0) * 100,
      format: 'percent',
      goodWhenPositive: false,
    },
  ]
}
