/**
 * Role-based view helpers for analytics pages.
 *
 * These pure functions encapsulate the logic that determines whether a user
 * should see tutor-only coaching content (nudges, recommendations, rubric) or
 * the simplified student-facing engagement summary.
 */
import type { UserRole } from './auth-types'

/**
 * Returns true when the viewer is a student.
 * When true, coaching-only sections (nudge history, recommendations, coaching
 * lenses rubric, portfolio comparison) should be hidden.
 */
export function isStudentAnalyticsView(role: UserRole | undefined | null): boolean {
  return role === 'student'
}

/**
 * Returns the analytics portfolio page heading based on the viewer's role.
 */
export function getAnalyticsPortfolioHeading(role: UserRole | undefined | null): string {
  return role === 'student'
    ? 'Your session history'
    : 'Post-session analytics redesigned for actual coaching follow-up.'
}

/**
 * Returns the analytics portfolio page sub-description based on the viewer's role.
 */
export function getAnalyticsPortfolioDescription(role: UserRole | undefined | null): string {
  return role === 'student'
    ? 'Review your engagement, attention, and participation across your tutoring sessions.'
    : 'Scan risk hotspots, compare recent sessions, and drill into recommendations without turning the live call into a dashboard.'
}

/**
 * Returns the analytics detail page title based on the viewer's role.
 * Tutors see "{tutor_id} · session review"; students see "Session summary".
 */
export function getAnalyticsDetailTitle(
  role: UserRole | undefined | null,
  tutorId: string | undefined
): string {
  if (role === 'student') return 'Session summary'
  return `${tutorId || 'Unassigned tutor'} · session review`
}
