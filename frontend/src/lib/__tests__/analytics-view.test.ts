/**
 * Tests for analytics-view.ts role-based display helpers.
 *
 * These pure functions determine which sections are visible to tutors vs
 * students in the analytics pages.
 */
import { describe, expect, it } from 'vitest'
import {
  getAnalyticsDetailTitle,
  getAnalyticsPortfolioDescription,
  getAnalyticsPortfolioHeading,
  isStudentAnalyticsView,
} from '../analytics-view'

describe('isStudentAnalyticsView', () => {
  it('returns true for student role', () => {
    expect(isStudentAnalyticsView('student')).toBe(true)
  })

  it('returns false for tutor role', () => {
    expect(isStudentAnalyticsView('tutor')).toBe(false)
  })

  it('returns false for guest role', () => {
    expect(isStudentAnalyticsView('guest')).toBe(false)
  })

  it('returns false for undefined role', () => {
    expect(isStudentAnalyticsView(undefined)).toBe(false)
  })

  it('returns false for null role', () => {
    expect(isStudentAnalyticsView(null)).toBe(false)
  })
})

describe('getAnalyticsPortfolioHeading', () => {
  it('returns student heading for student role', () => {
    expect(getAnalyticsPortfolioHeading('student')).toBe('Your session history')
  })

  it('returns tutor heading for tutor role', () => {
    const heading = getAnalyticsPortfolioHeading('tutor')
    expect(heading).toContain('analytics')
  })

  it('returns tutor heading for undefined role (default to tutor view)', () => {
    const heading = getAnalyticsPortfolioHeading(undefined)
    expect(heading).not.toBe('Your session history')
  })

  it('returns different headings for tutor and student', () => {
    expect(getAnalyticsPortfolioHeading('tutor')).not.toBe(
      getAnalyticsPortfolioHeading('student')
    )
  })
})

describe('getAnalyticsPortfolioDescription', () => {
  it('returns student-focused copy for student role', () => {
    const desc = getAnalyticsPortfolioDescription('student')
    expect(desc).toContain('engagement')
    expect(desc).toContain('participation')
  })

  it('returns tutor-focused copy for tutor role', () => {
    const desc = getAnalyticsPortfolioDescription('tutor')
    expect(desc).toContain('recommendations')
  })

  it('returns different descriptions for tutor and student', () => {
    expect(getAnalyticsPortfolioDescription('tutor')).not.toBe(
      getAnalyticsPortfolioDescription('student')
    )
  })
})

describe('getAnalyticsDetailTitle', () => {
  it('returns "Session summary" for student role', () => {
    expect(getAnalyticsDetailTitle('student', 'Alice')).toBe('Session summary')
  })

  it('returns tutor name + review for tutor role', () => {
    expect(getAnalyticsDetailTitle('tutor', 'Alice')).toBe('Alice · session review')
  })

  it('returns fallback when tutor_id is empty for tutor role', () => {
    expect(getAnalyticsDetailTitle('tutor', '')).toBe('Unassigned tutor · session review')
  })

  it('returns fallback when tutor_id is undefined for tutor role', () => {
    expect(getAnalyticsDetailTitle('tutor', undefined)).toBe(
      'Unassigned tutor · session review'
    )
  })

  it('ignores tutor_id for student role', () => {
    expect(getAnalyticsDetailTitle('student', 'Any Tutor')).toBe('Session summary')
    expect(getAnalyticsDetailTitle('student', '')).toBe('Session summary')
    expect(getAnalyticsDetailTitle('student', undefined)).toBe('Session summary')
  })

  it('returns tutor view for undefined role (default)', () => {
    const title = getAnalyticsDetailTitle(undefined, 'Bob')
    expect(title).toContain('Bob')
    expect(title).not.toBe('Session summary')
  })
})
