import { beforeEach, describe, expect, it } from 'vitest'
import { getTutorId, getTutorName, setTutorName } from '../tutor-identity'

describe('tutor identity persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns an empty tutor name when nothing is stored', () => {
    expect(getTutorName()).toBe('')
  })

  it('saves and reads the tutor name', () => {
    setTutorName('Ada Lovelace')

    expect(getTutorName()).toBe('Ada Lovelace')
  })

  it('generates and persists a tutor id on first read', () => {
    const tutorId = getTutorId()

    expect(tutorId).toHaveLength(8)
    expect(localStorage.getItem('tutor_id')).toBe(tutorId)
    expect(getTutorId()).toBe(tutorId)
  })
})
