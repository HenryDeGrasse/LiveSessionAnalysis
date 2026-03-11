import { describe, expect, it } from 'vitest'
import type { SessionSummary } from '../types'
import {
  ATTENTION_STATES,
  average,
  classifyTrend,
  computeAttentionDistributionFallback,
  deriveActionQueue,
  deriveComparisonDeltas,
  deriveDashboardOverview,
  deriveSessionRubric,
  deriveTrendSnapshot,
  formatAttentionState,
  formatClock,
  formatDelta,
  formatMinutes,
  formatNudgePriority,
  formatPercent,
  formatScore,
  getSessionHealth,
  getSessionTypeLabel,
  getTrendLabel,
  getTrendTone,
  getTutorTalkTarget,
  getTutorTalkTolerance,
  isTalkBalanced,
} from '../analytics'

const baseSession: SessionSummary = {
  session_id: 'session-1',
  tutor_id: 'tutor-1',
  start_time: '2026-03-10T12:00:00.000Z',
  end_time: '2026-03-10T12:30:00.000Z',
  duration_seconds: 1800,
  session_type: 'general',
  media_provider: 'livekit',
  talk_time_ratio: { tutor: 0.6, student: 0.4 },
  avg_eye_contact: { tutor: 0.75, student: 0.55 },
  avg_energy: { tutor: 0.72, student: 0.61 },
  total_interruptions: 2,
  engagement_score: 76,
  flagged_moments: [],
  timeline: {},
  recommendations: [],
  nudges_sent: 1,
  degradation_events: 0,
}

function makeSession(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return { ...baseSession, ...overrides }
}

// ── Attention state helpers ─────────────────────────────────
describe('analytics helpers', () => {
  it('formats known attention states into human-readable labels', () => {
    expect(formatAttentionState('CAMERA_FACING')).toBe('Camera-facing')
    expect(formatAttentionState('OFF_TASK_AWAY')).toBe('Off-task / away')
    expect(formatAttentionState('LOW_CONFIDENCE')).toBe('Low confidence')
  })

  it('falls back to a readable label for unknown attention states', () => {
    expect(formatAttentionState('CUSTOM_STATE')).toBe('Custom State')
  })

  it('maps nudge priorities to the expected tones', () => {
    expect(formatNudgePriority('low')).toEqual({
      label: 'Low priority',
      tone: 'slate',
    })
    expect(formatNudgePriority('medium')).toEqual({
      label: 'Medium priority',
      tone: 'amber',
    })
    expect(formatNudgePriority('high')).toEqual({
      label: 'High priority',
      tone: 'rose',
    })
  })

  it('exposes the expected 6 canonical attention states', () => {
    expect(ATTENTION_STATES).toEqual([
      'CAMERA_FACING',
      'SCREEN_ENGAGED',
      'DOWN_ENGAGED',
      'OFF_TASK_AWAY',
      'FACE_MISSING',
      'LOW_CONFIDENCE',
    ])
    expect(ATTENTION_STATES).toHaveLength(6)
  })

  it('returns null when attention state distribution is missing', () => {
    expect(computeAttentionDistributionFallback(baseSession)).toBeNull()
  })
})

// ── formatPercent ───────────────────────────────────────────
describe('formatPercent', () => {
  it('formats a ratio as a percentage with default 0 digits', () => {
    expect(formatPercent(0.75)).toBe('75%')
  })

  it('formats with specified decimal digits', () => {
    expect(formatPercent(0.756, 1)).toBe('75.6%')
    expect(formatPercent(0.756, 2)).toBe('75.60%')
  })

  it('formats 0 and 1 correctly', () => {
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(1)).toBe('100%')
  })
})

// ── formatScore ─────────────────────────────────────────────
describe('formatScore', () => {
  it('formats a number with default 0 digits', () => {
    expect(formatScore(72.8)).toBe('73')
  })

  it('formats with specified decimal digits', () => {
    expect(formatScore(72.83, 1)).toBe('72.8')
    expect(formatScore(72.83, 2)).toBe('72.83')
  })
})

// ── formatMinutes ───────────────────────────────────────────
describe('formatMinutes', () => {
  it('formats durations under 60 seconds as seconds', () => {
    expect(formatMinutes(45)).toBe('45 sec')
    expect(formatMinutes(1)).toBe('1 sec')
  })

  it('formats durations at or above 60 seconds as minutes', () => {
    expect(formatMinutes(60)).toBe('1 min')
    expect(formatMinutes(1800)).toBe('30 min')
    expect(formatMinutes(90)).toBe('2 min')
  })
})

// ── formatClock ─────────────────────────────────────────────
describe('formatClock', () => {
  it('formats total seconds as mm:ss', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(65)).toBe('1:05')
    expect(formatClock(600)).toBe('10:00')
    expect(formatClock(3661)).toBe('61:01')
  })
})

// ── formatDelta ─────────────────────────────────────────────
describe('formatDelta', () => {
  it('formats score deltas with +/- prefix', () => {
    expect(formatDelta(5, 'score')).toBe('+5')
    expect(formatDelta(-3, 'score')).toBe('-3')
    expect(formatDelta(0, 'score')).toBe('0')
  })

  it('formats percent deltas with pp suffix', () => {
    expect(formatDelta(12, 'percent')).toBe('+12 pp')
    expect(formatDelta(-7, 'percent')).toBe('-7 pp')
  })

  it('formats count deltas with one decimal', () => {
    expect(formatDelta(2.5, 'count')).toBe('+2.5')
    expect(formatDelta(-1.3, 'count')).toBe('-1.3')
  })
})

// ── average ─────────────────────────────────────────────────
describe('average', () => {
  it('returns 0 for an empty array', () => {
    expect(average([])).toBe(0)
  })

  it('computes the arithmetic mean', () => {
    expect(average([10, 20, 30])).toBe(20)
    expect(average([5])).toBe(5)
  })
})

// ── getSessionTypeLabel ─────────────────────────────────────
describe('getSessionTypeLabel', () => {
  it('returns human-readable labels for known session types', () => {
    expect(getSessionTypeLabel('general')).toBe('General tutoring')
    expect(getSessionTypeLabel('lecture')).toBe('Lecture / explanation')
    expect(getSessionTypeLabel('practice')).toBe('Practice / problem solving')
    expect(getSessionTypeLabel('discussion')).toBe('Discussion / Socratic')
  })

  it('returns the raw string for unknown session types', () => {
    expect(getSessionTypeLabel('workshop')).toBe('workshop')
  })

  it('returns default label for empty string', () => {
    expect(getSessionTypeLabel('')).toBe('General tutoring')
  })
})

// ── getTutorTalkTarget / getTutorTalkTolerance ──────────────
describe('getTutorTalkTarget', () => {
  it('returns known targets for each session type', () => {
    expect(getTutorTalkTarget('general')).toBe(0.65)
    expect(getTutorTalkTarget('lecture')).toBe(0.8)
    expect(getTutorTalkTarget('practice')).toBe(0.5)
    expect(getTutorTalkTarget('discussion')).toBe(0.55)
  })

  it('falls back to general target for unknown types', () => {
    expect(getTutorTalkTarget('unknown')).toBe(0.65)
  })
})

describe('getTutorTalkTolerance', () => {
  it('returns known tolerances for each session type', () => {
    expect(getTutorTalkTolerance('general')).toBe(0.12)
    expect(getTutorTalkTolerance('lecture')).toBe(0.1)
    expect(getTutorTalkTolerance('practice')).toBe(0.12)
    expect(getTutorTalkTolerance('discussion')).toBe(0.1)
  })

  it('falls back to general tolerance for unknown types', () => {
    expect(getTutorTalkTolerance('unknown')).toBe(0.12)
  })
})

// ── getTrendTone / getTrendLabel ────────────────────────────
describe('getTrendTone', () => {
  it('maps trend directions to the correct tones', () => {
    expect(getTrendTone('improving')).toBe('emerald')
    expect(getTrendTone('declining')).toBe('rose')
    expect(getTrendTone('stable')).toBe('slate')
  })
})

describe('getTrendLabel', () => {
  it('maps trend directions to the correct labels', () => {
    expect(getTrendLabel('improving')).toBe('Improving')
    expect(getTrendLabel('declining')).toBe('Declining')
    expect(getTrendLabel('stable')).toBe('Stable')
  })
})

// ── isTalkBalanced ──────────────────────────────────────────
describe('isTalkBalanced', () => {
  it('returns true when tutor talk is within tolerance of general target', () => {
    // general target = 0.65, tolerance = 0.12 → range [0.53, 0.77]
    expect(isTalkBalanced(makeSession({ talk_time_ratio: { tutor: 0.65, student: 0.35 } }))).toBe(true)
    expect(isTalkBalanced(makeSession({ talk_time_ratio: { tutor: 0.6, student: 0.4 } }))).toBe(true)
  })

  it('returns false when tutor talk is outside tolerance for general', () => {
    expect(isTalkBalanced(makeSession({ talk_time_ratio: { tutor: 0.9, student: 0.1 } }))).toBe(false)
    expect(isTalkBalanced(makeSession({ talk_time_ratio: { tutor: 0.4, student: 0.6 } }))).toBe(false)
  })

  it('returns true when lecture tutor talk is within tolerance', () => {
    // lecture target = 0.8, tolerance = 0.1 → range [0.7, 0.9]
    const lectureSession = makeSession({
      session_type: 'lecture',
      talk_time_ratio: { tutor: 0.82, student: 0.18 },
    })
    expect(isTalkBalanced(lectureSession)).toBe(true)
  })

  it('returns false when lecture tutor talk is outside tolerance', () => {
    const lectureTooLow = makeSession({
      session_type: 'lecture',
      talk_time_ratio: { tutor: 0.6, student: 0.4 },
    })
    expect(isTalkBalanced(lectureTooLow)).toBe(false)
  })

  it('returns true when practice tutor talk is within tolerance', () => {
    // practice target = 0.5, tolerance = 0.12 → range [0.38, 0.62]
    const practiceBalanced = makeSession({
      session_type: 'practice',
      talk_time_ratio: { tutor: 0.5, student: 0.5 },
    })
    expect(isTalkBalanced(practiceBalanced)).toBe(true)
  })

  it('returns false when practice tutor talk is outside tolerance', () => {
    const practiceHigh = makeSession({
      session_type: 'practice',
      talk_time_ratio: { tutor: 0.75, student: 0.25 },
    })
    expect(isTalkBalanced(practiceHigh)).toBe(false)
  })

  it('returns true when discussion tutor talk is within tolerance', () => {
    // discussion target = 0.55, tolerance = 0.1 → range [0.45, 0.65]
    const discussionBalanced = makeSession({
      session_type: 'discussion',
      talk_time_ratio: { tutor: 0.55, student: 0.45 },
    })
    expect(isTalkBalanced(discussionBalanced)).toBe(true)
  })

  it('returns false when discussion tutor talk is outside tolerance', () => {
    const discussionHigh = makeSession({
      session_type: 'discussion',
      talk_time_ratio: { tutor: 0.8, student: 0.2 },
    })
    expect(isTalkBalanced(discussionHigh)).toBe(false)
  })
})

// ── getSessionHealth ────────────────────────────────────────
describe('getSessionHealth', () => {
  it('returns "On track" for high engagement and low severity', () => {
    const health = getSessionHealth(makeSession({
      engagement_score: 80,
      avg_eye_contact: { tutor: 0.8, student: 0.6 },
      total_interruptions: 1,
      nudges_sent: 0,
    }))
    expect(health.label).toBe('On track')
    expect(health.tone).toBe('emerald')
  })

  it('returns "Watchlist" for moderate severity', () => {
    const health = getSessionHealth(makeSession({
      engagement_score: 65,
      avg_eye_contact: { tutor: 0.7, student: 0.25 }, // student < 0.3 → severity +2
      total_interruptions: 2,
      nudges_sent: 1,
    }))
    expect(health.label).toBe('Watchlist')
    expect(health.tone).toBe('amber')
  })

  it('returns "Needs review" for low engagement and high severity', () => {
    const health = getSessionHealth(makeSession({
      engagement_score: 40,
      avg_eye_contact: { tutor: 0.5, student: 0.2 },
      total_interruptions: 8,
      talk_time_ratio: { tutor: 0.95, student: 0.05 },
      nudges_sent: 3,
    }))
    expect(health.label).toBe('Needs review')
    expect(health.tone).toBe('rose')
  })

  it('includes a severity-based score', () => {
    const healthy = getSessionHealth(makeSession({ engagement_score: 80 }))
    const poor = getSessionHealth(makeSession({
      engagement_score: 40,
      avg_eye_contact: { tutor: 0.5, student: 0.2 },
      total_interruptions: 8,
    }))
    expect(healthy.score).toBeGreaterThan(poor.score)
  })
})

// ── classifyTrend ───────────────────────────────────────────
describe('classifyTrend', () => {
  it('returns "stable" for a single value', () => {
    expect(classifyTrend([50])).toBe('stable')
  })

  it('returns "stable" for constant values', () => {
    expect(classifyTrend([50, 50, 50, 50])).toBe('stable')
  })

  it('detects an improving trend', () => {
    expect(classifyTrend([10, 20, 30, 40, 50])).toBe('improving')
  })

  it('detects a declining trend', () => {
    expect(classifyTrend([50, 40, 30, 20, 10])).toBe('declining')
  })

  it('inverts direction when inverted=true', () => {
    // Decreasing values with inverted=true → improving (e.g., fewer interruptions)
    expect(classifyTrend([50, 40, 30, 20, 10], true)).toBe('improving')
    // Increasing values with inverted=true → declining
    expect(classifyTrend([10, 20, 30, 40, 50], true)).toBe('declining')
  })

  it('returns "stable" for small fluctuations', () => {
    expect(classifyTrend([50, 51, 49, 50, 51])).toBe('stable')
  })
})

// ── deriveTrendSnapshot ─────────────────────────────────────
describe('deriveTrendSnapshot', () => {
  it('derives trends from chronologically sorted sessions', () => {
    const sessions = [
      makeSession({
        session_id: 's1',
        start_time: '2026-03-08T10:00:00Z',
        engagement_score: 50,
        avg_eye_contact: { tutor: 0.7, student: 0.3 },
        total_interruptions: 8,
        talk_time_ratio: { tutor: 0.9, student: 0.1 },
      }),
      makeSession({
        session_id: 's2',
        start_time: '2026-03-09T10:00:00Z',
        engagement_score: 60,
        avg_eye_contact: { tutor: 0.7, student: 0.4 },
        total_interruptions: 5,
        talk_time_ratio: { tutor: 0.8, student: 0.2 },
      }),
      makeSession({
        session_id: 's3',
        start_time: '2026-03-10T10:00:00Z',
        engagement_score: 75,
        avg_eye_contact: { tutor: 0.7, student: 0.55 },
        total_interruptions: 2,
        talk_time_ratio: { tutor: 0.65, student: 0.35 },
      }),
    ]

    const trends = deriveTrendSnapshot(sessions)
    expect(trends.engagement).toBe('improving')
    expect(trends.studentEye).toBe('improving')
    expect(trends.interruptions).toBe('improving') // inverted: fewer is better
  })

  it('sorts sessions chronologically regardless of input order', () => {
    const sessions = [
      makeSession({ session_id: 's2', start_time: '2026-03-10T10:00:00Z', engagement_score: 80 }),
      makeSession({ session_id: 's1', start_time: '2026-03-08T10:00:00Z', engagement_score: 40 }),
    ]

    const trends = deriveTrendSnapshot(sessions)
    expect(trends.engagement).toBe('improving')
  })
})

// ── deriveDashboardOverview ─────────────────────────────────
describe('deriveDashboardOverview', () => {
  it('computes overview from multiple sessions', () => {
    const sessions = [
      makeSession({ engagement_score: 80, total_interruptions: 2 }),
      makeSession({
        session_id: 's2',
        engagement_score: 60,
        total_interruptions: 6,
        avg_eye_contact: { tutor: 0.5, student: 0.2 },
      }),
    ]

    const overview = deriveDashboardOverview(sessions)
    expect(overview.totalSessions).toBe(2)
    expect(overview.averageEngagement).toBe(70)
    expect(overview.averageInterruptions).toBe(4)
    expect(overview.averageDurationMinutes).toBe(30) // 1800s each
  })

  it('returns zeroes for an empty array', () => {
    const overview = deriveDashboardOverview([])
    expect(overview.totalSessions).toBe(0)
    expect(overview.averageEngagement).toBe(0)
    expect(overview.averageStudentEye).toBe(0)
    expect(overview.sessionsNeedingReview).toBe(0)
  })

  it('counts sessions needing review', () => {
    const sessions = [
      makeSession({ engagement_score: 80 }), // On track
      makeSession({
        session_id: 's2',
        engagement_score: 40,
        avg_eye_contact: { tutor: 0.5, student: 0.2 },
        total_interruptions: 8,
      }), // Needs review
    ]

    const overview = deriveDashboardOverview(sessions)
    expect(overview.sessionsNeedingReview).toBe(1)
  })

  it('computes balanced talk rate', () => {
    const sessions = [
      makeSession({ talk_time_ratio: { tutor: 0.65, student: 0.35 } }), // balanced
      makeSession({
        session_id: 's2',
        talk_time_ratio: { tutor: 0.95, student: 0.05 },
      }), // unbalanced
    ]

    const overview = deriveDashboardOverview(sessions)
    expect(overview.balancedTalkRate).toBe(0.5) // 1 out of 2 balanced
  })
})

// ── deriveActionQueue ───────────────────────────────────────
describe('deriveActionQueue', () => {
  it('sorts items by severity descending', () => {
    const sessions = [
      makeSession({
        session_id: 'low-sev',
        engagement_score: 70,
        total_interruptions: 6, // severity +2
        nudges_sent: 0,
      }),
      makeSession({
        session_id: 'high-sev',
        engagement_score: 40,
        avg_eye_contact: { tutor: 0.5, student: 0.2 },
        total_interruptions: 8,
        talk_time_ratio: { tutor: 0.95, student: 0.05 },
      }),
    ]

    const queue = deriveActionQueue(sessions)
    expect(queue.length).toBeGreaterThan(0)
    expect(queue[0].sessionId).toBe('high-sev')
    // Verify descending order
    for (let i = 1; i < queue.length; i++) {
      expect(queue[i - 1].severity).toBeGreaterThanOrEqual(queue[i].severity)
    }
  })

  it('caps at 4 items', () => {
    const sessions = Array.from({ length: 10 }, (_, i) =>
      makeSession({
        session_id: `s${i}`,
        engagement_score: 40,
        total_interruptions: 8,
      })
    )

    const queue = deriveActionQueue(sessions)
    expect(queue.length).toBeLessThanOrEqual(4)
  })

  it('filters out healthy sessions with zero severity', () => {
    const sessions = [
      makeSession({ engagement_score: 85, total_interruptions: 0, nudges_sent: 0 }),
    ]

    const queue = deriveActionQueue(sessions)
    expect(queue).toHaveLength(0)
  })

  it('returns empty array for empty input', () => {
    expect(deriveActionQueue([])).toEqual([])
  })
})

// ── deriveSessionRubric ─────────────────────────────────────
describe('deriveSessionRubric', () => {
  it('returns exactly 4 rubric scores', () => {
    const rubric = deriveSessionRubric(baseSession)
    expect(rubric).toHaveLength(4)
    expect(rubric.map((r) => r.label)).toEqual([
      'Conversation balance',
      'Student presence',
      'Turn-taking control',
      'Live coach load',
    ])
  })

  it('gives high conversation balance when tutor talk matches target', () => {
    const balanced = makeSession({
      session_type: 'general',
      talk_time_ratio: { tutor: 0.65, student: 0.35 },
    })
    const rubric = deriveSessionRubric(balanced)
    expect(rubric[0].value).toBe(100) // exactly at target
  })

  it('gives lower conversation balance when tutor talk deviates from target', () => {
    const unbalanced = makeSession({
      session_type: 'general',
      talk_time_ratio: { tutor: 0.95, student: 0.05 },
    })
    const rubric = deriveSessionRubric(unbalanced)
    expect(rubric[0].value).toBeLessThan(50)
  })

  it('penalizes turn-taking control for many interruptions', () => {
    const session = makeSession({ total_interruptions: 8 })
    const rubric = deriveSessionRubric(session)
    const turnTaking = rubric.find((r) => r.label === 'Turn-taking control')!
    expect(turnTaking.value).toBeLessThan(10) // 100 - 8*12 = 4
  })

  it('penalizes coaching load for many nudges', () => {
    const session = makeSession({ nudges_sent: 5 })
    const rubric = deriveSessionRubric(session)
    const coachLoad = rubric.find((r) => r.label === 'Live coach load')!
    expect(coachLoad.value).toBeLessThan(20) // 100 - 5*18 = 10
  })

  it('clamps rubric values between 0 and 100', () => {
    const extreme = makeSession({ total_interruptions: 100, nudges_sent: 100 })
    const rubric = deriveSessionRubric(extreme)
    rubric.forEach((r) => {
      expect(r.value).toBeGreaterThanOrEqual(0)
      expect(r.value).toBeLessThanOrEqual(100)
    })
  })
})

// ── deriveComparisonDeltas ──────────────────────────────────
describe('deriveComparisonDeltas', () => {
  it('returns null for empty peers', () => {
    expect(deriveComparisonDeltas(baseSession, [])).toBeNull()
  })

  it('computes deltas against peer averages', () => {
    const peers = [
      makeSession({ engagement_score: 60, avg_eye_contact: { tutor: 0.7, student: 0.4 } }),
      makeSession({
        session_id: 's2',
        engagement_score: 80,
        avg_eye_contact: { tutor: 0.7, student: 0.6 },
      }),
    ]
    // peer avg engagement = 70, session engagement = 76 → delta = +6
    const deltas = deriveComparisonDeltas(baseSession, peers)
    expect(deltas).not.toBeNull()
    expect(deltas!).toHaveLength(4)

    const engagement = deltas!.find((d) => d.label === 'Engagement vs baseline')!
    expect(engagement.delta).toBe(6) // 76 - 70
    expect(engagement.format).toBe('score')
    expect(engagement.goodWhenPositive).toBe(true)
  })

  it('returns 4 delta categories', () => {
    const peers = [makeSession({ session_id: 'peer-1' })]
    const deltas = deriveComparisonDeltas(baseSession, peers)!
    expect(deltas.map((d) => d.label)).toEqual([
      'Engagement vs baseline',
      'Student camera-facing',
      'Interruptions',
      'Tutor talk share',
    ])
  })

  it('marks interruptions as good when negative', () => {
    const peers = [makeSession({ session_id: 'peer-1' })]
    const deltas = deriveComparisonDeltas(baseSession, peers)!
    const interruptions = deltas.find((d) => d.label === 'Interruptions')!
    expect(interruptions.goodWhenPositive).toBe(false)
  })
})

// ── computeAttentionDistributionFallback ────────────────────
describe('computeAttentionDistributionFallback', () => {
  it('returns student distribution when available', () => {
    const session = makeSession({
      attention_state_distribution: {
        student: { CAMERA_FACING: 0.6, OFF_TASK_AWAY: 0.4 },
        tutor: { CAMERA_FACING: 0.9 },
      },
    })
    const result = computeAttentionDistributionFallback(session)
    expect(result).toEqual({ CAMERA_FACING: 0.6, OFF_TASK_AWAY: 0.4 })
  })

  it('falls back to tutor distribution when student is empty', () => {
    const session = makeSession({
      attention_state_distribution: {
        student: {},
        tutor: { CAMERA_FACING: 0.9 },
      },
    })
    const result = computeAttentionDistributionFallback(session)
    expect(result).toEqual({ CAMERA_FACING: 0.9 })
  })

  it('returns null for empty distribution object', () => {
    const session = makeSession({ attention_state_distribution: {} })
    expect(computeAttentionDistributionFallback(session)).toBeNull()
  })
})

// ── formatNudgePriority edge cases ──────────────────────────
describe('formatNudgePriority edge cases', () => {
  it('handles unknown priorities with fallback', () => {
    const result = formatNudgePriority('critical')
    expect(result.label).toBe('Critical priority')
    expect(result.tone).toBe('slate')
  })

  it('handles empty string', () => {
    const result = formatNudgePriority('')
    expect(result.label).toBe('Priority')
    expect(result.tone).toBe('slate')
  })

  it('handles whitespace-padded priorities', () => {
    expect(formatNudgePriority('  high  ')).toEqual({
      label: 'High priority',
      tone: 'rose',
    })
  })
})
