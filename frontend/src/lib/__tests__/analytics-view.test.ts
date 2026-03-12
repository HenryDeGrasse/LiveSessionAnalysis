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
  const session = {
    session_title: 'Algebra review · Jan 1, 10:00 AM',
    session_type: 'general',
    start_time: '2026-01-01T10:00:00Z',
  }

  it('returns the session title for student role', () => {
    expect(getAnalyticsDetailTitle('student', session)).toBe(session.session_title)
  })

  it('returns the session title for tutor role', () => {
    expect(getAnalyticsDetailTitle('tutor', session)).toBe(session.session_title)
  })

  it('falls back to generated title when session_title is empty', () => {
    const title = getAnalyticsDetailTitle('tutor', {
      session_title: '',
      session_type: 'practice',
      start_time: '2026-01-01T10:00:00Z',
    })
    expect(title).toContain('Practice')
  })

  it('returns tutor view for undefined role (default)', () => {
    const title = getAnalyticsDetailTitle(undefined, session)
    expect(title).toContain('Algebra review')
  })
})
