const TUTOR_NAME_KEY = 'tutor_name'
const TUTOR_ID_KEY = 'tutor_id'

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

function generateTutorId() {
  if (
    typeof globalThis !== 'undefined' &&
    'crypto' in globalThis &&
    typeof globalThis.crypto?.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID().replace(/-/g, '').slice(0, 8)
  }

  return Math.random().toString(36).slice(2, 10)
}

export function getTutorName(): string {
  const storage = getStorage()
  return storage?.getItem(TUTOR_NAME_KEY) || ''
}

export function setTutorName(name: string): void {
  const storage = getStorage()
  if (!storage) return
  storage.setItem(TUTOR_NAME_KEY, name)
}

export function getTutorId(): string {
  const storage = getStorage()
  const existingId = storage?.getItem(TUTOR_ID_KEY)

  if (existingId) {
    return existingId
  }

  const tutorId = generateTutorId()
  storage?.setItem(TUTOR_ID_KEY, tutorId)
  return tutorId
}
