import { describe, expect, it } from 'vitest'
import { coachingStatusSummary } from '../coaching-status'

describe('coachingStatusSummary', () => {
  it('returns null when coaching_status is absent', () => {
    expect(coachingStatusSummary({ coaching_status: undefined })).toBeNull()
  })

  it('returns null when coaching_status is null', () => {
    expect(coachingStatusSummary({ coaching_status: null })).toBeNull()
  })

  it('returns "Budget used" pill when budget_remaining is 0', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 0,
        next_eligible_s: 0,
        rules_evaluated: 5,
        budget_remaining: 0,
      },
    })
    expect(result).not.toBeNull()
    expect(result!.label).toBe('Coaching')
    expect(result!.value).toBe('Budget used')
    expect(result!.className).toContain('text-gray-100')
  })

  it('budget_remaining === 0 takes priority over warmup', () => {
    // Even if warmup is still running, budget=0 should show "Budget used"
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 45,
        next_eligible_s: 0,
        rules_evaluated: 0,
        budget_remaining: 0,
      },
    })
    expect(result!.value).toBe('Budget used')
  })

  it('returns warmup pill with rounded-up seconds when not active and warmup > 0', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 87.3,
        next_eligible_s: 0,
        rules_evaluated: 0,
        budget_remaining: 3,
      },
    })
    expect(result).not.toBeNull()
    expect(result!.label).toBe('Coaching')
    expect(result!.value).toBe('Warming up (88s)')
    expect(result!.className).toContain('text-sky-100')
  })

  it('rounds fractional warmup seconds up', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 1.1,
        next_eligible_s: 0,
        rules_evaluated: 0,
        budget_remaining: 2,
      },
    })
    expect(result!.value).toBe('Warming up (2s)')
  })

  it('returns "Active" pill when active and budget remains', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: true,
        warmup_remaining_s: 0,
        next_eligible_s: 0,
        rules_evaluated: 3,
        budget_remaining: 2,
      },
    })
    expect(result).not.toBeNull()
    expect(result!.label).toBe('Coaching')
    expect(result!.value).toBe('Active')
    expect(result!.className).toContain('text-emerald-100')
  })

  it('returns cooldown pill when warmup is done but the global nudge interval is still active', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 0,
        next_eligible_s: 30,
        rules_evaluated: 1,
        budget_remaining: 1,
      },
    })
    expect(result!.value).toBe('Cooling down (30s)')
    expect(result!.className).toContain('text-amber-100')
  })

  it('returns paused when coaching is inactive without warmup, cooldown, or budget exhaustion', () => {
    const result = coachingStatusSummary({
      coaching_status: {
        active: false,
        warmup_remaining_s: 0,
        next_eligible_s: 0,
        rules_evaluated: 0,
        budget_remaining: 4,
      },
    })
    expect(result!.value).toBe('Paused')
    expect(result!.className).toContain('text-gray-100')
  })
})
