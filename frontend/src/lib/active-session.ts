const ACTIVE_SESSION_KEY = 'active_session'
const ACTIVE_SESSION_MAX_AGE_MS = 4 * 60 * 60 * 1000

export interface ActiveSession {
  session_id: string
  tutor_token: string
  created_at: string
}

function getStorage(): Storage | null {
  if (typeof globalThis === 'undefined' || !('localStorage' in globalThis)) {
    return null
  }

  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

export function saveActiveSession(
  sessionId: string,
  tutorToken: string
): void {
  const storage = getStorage()
  if (!storage) return

  const payload: ActiveSession = {
    session_id: sessionId,
    tutor_token: tutorToken,
    created_at: new Date().toISOString(),
  }

  storage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(payload))
}

export function getActiveSession(): ActiveSession | null {
  const storage = getStorage()
  if (!storage) return null

  const rawSession = storage.getItem(ACTIVE_SESSION_KEY)
  if (!rawSession) return null

  try {
    const parsed = JSON.parse(rawSession) as Partial<ActiveSession>

    if (!parsed.session_id || !parsed.tutor_token || !parsed.created_at) {
      storage.removeItem(ACTIVE_SESSION_KEY)
      return null
    }

    const createdAt = new Date(parsed.created_at).getTime()
    if (
      !Number.isFinite(createdAt) ||
      Date.now() - createdAt > ACTIVE_SESSION_MAX_AGE_MS
    ) {
      storage.removeItem(ACTIVE_SESSION_KEY)
      return null
    }

    return {
      session_id: parsed.session_id,
      tutor_token: parsed.tutor_token,
      created_at: parsed.created_at,
    }
  } catch {
    storage.removeItem(ACTIVE_SESSION_KEY)
    return null
  }
}

export function clearActiveSession(): void {
  const storage = getStorage()
  if (!storage) return
  storage.removeItem(ACTIVE_SESSION_KEY)
}
