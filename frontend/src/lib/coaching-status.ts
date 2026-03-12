import type { MetricsSnapshot } from './types'

export type CoachingStatusPill = {
  label: 'Coaching'
  value: string
  className: string
}

export function coachingStatusSummary(
  metrics: Pick<MetricsSnapshot, 'coaching_status'>
): CoachingStatusPill | null {
  const coachingStatus = metrics.coaching_status
  if (!coachingStatus) return null

  if (coachingStatus.budget_remaining === 0) {
    return {
      label: 'Coaching',
      value: 'Budget used',
      className:
        'border-gray-400/30 bg-gray-500/10 text-gray-100 shadow-[0_0_18px_rgba(148,163,184,0.12)]',
    }
  }

  if (!coachingStatus.active && coachingStatus.warmup_remaining_s > 0) {
    return {
      label: 'Coaching',
      value: `Warming up (${Math.ceil(coachingStatus.warmup_remaining_s)}s)`,
      className:
        'border-sky-400/30 bg-sky-500/10 text-sky-100 shadow-[0_0_18px_rgba(56,189,248,0.12)]',
    }
  }

  if (!coachingStatus.active && coachingStatus.next_eligible_s > 0) {
    return {
      label: 'Coaching',
      value: `Cooling down (${Math.ceil(coachingStatus.next_eligible_s)}s)`,
      className:
        'border-amber-400/30 bg-amber-500/10 text-amber-100 shadow-[0_0_18px_rgba(245,158,11,0.12)]',
    }
  }

  if (!coachingStatus.active) {
    return {
      label: 'Coaching',
      value: 'Paused',
      className:
        'border-gray-400/30 bg-gray-500/10 text-gray-100 shadow-[0_0_18px_rgba(148,163,184,0.12)]',
    }
  }

  return {
    label: 'Coaching',
    value: 'Active',
    className:
      'border-emerald-400/40 bg-emerald-500/10 text-emerald-100 shadow-[0_0_22px_rgba(16,185,129,0.18)]',
  }
}
