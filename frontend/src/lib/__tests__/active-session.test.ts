import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearActiveSession,
  getActiveSession,
  saveActiveSession,
} from '../active-session'

describe('active session persistence', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useRealTimers()
  })

  afterEach(() => {
    localStorage.clear()
    vi.useRealTimers()
  })

  it('saves and loads the active session', () => {
    const now = new Date('2026-03-10T13:00:00.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)

    saveActiveSession('session-1', 'token-1')

    expect(getActiveSession()).toEqual({
      session_id: 'session-1',
      tutor_token: 'token-1',
      created_at: now.toISOString(),
    })
  })

  it('returns null when nothing is stored', () => {
    expect(getActiveSession()).toBeNull()
  })

  it('clears the active session entry', () => {
    saveActiveSession('session-1', 'token-1')
    clearActiveSession()

    expect(getActiveSession()).toBeNull()
    expect(localStorage.getItem('active_session')).toBeNull()
  })

  it('returns null for expired sessions older than 4 hours', () => {
    const now = new Date('2026-03-10T13:00:00.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)

    localStorage.setItem(
      'active_session',
      JSON.stringify({
        session_id: 'session-1',
        tutor_token: 'token-1',
        created_at: new Date(now.getTime() - 4 * 60 * 60 * 1000 - 1000).toISOString(),
      })
    )

    expect(getActiveSession()).toBeNull()
    expect(localStorage.getItem('active_session')).toBeNull()
  })
})
