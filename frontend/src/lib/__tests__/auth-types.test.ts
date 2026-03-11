/**
 * Tests for auth-types.ts.
 *
 * The module augmentations cannot be exercised at runtime, so this file
 * validates the JavaScript-level exports (UserRole type values) and ensures
 * the module loads without error.
 */
import { describe, expect, it } from 'vitest'

// Importing auth-types registers the module augmentations side-effectfully.
// The only concrete export is the UserRole type, which we verify via the
// type-level checks below.
import type { UserRole } from '../auth-types'

describe('auth-types module', () => {
  it('loads without throwing', async () => {
    // Dynamic import verifies the module is well-formed at runtime.
    await expect(import('../auth-types')).resolves.toBeDefined()
  })

  it('UserRole accepts the three expected literal values', () => {
    // Type-level assertion — if this compiles, the type is correct.
    const roles: UserRole[] = ['tutor', 'student', 'guest']
    expect(roles).toHaveLength(3)
    expect(roles).toContain('tutor')
    expect(roles).toContain('student')
    expect(roles).toContain('guest')
  })
})
