import { describe, expect, it } from 'vitest'
import type { SessionSummary } from '../types'
import {
  ATTENTION_STATES,
  computeAttentionDistributionFallback,
  formatAttentionState,
  formatNudgePriority,
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
