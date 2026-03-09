import { describe, expect, it } from 'vitest'
import { resolveMediaProvider } from './provider'

describe('resolveMediaProvider', () => {
  it('defaults to livekit when no override or session info', () => {
    expect(resolveMediaProvider(null)).toBe('livekit')
  })

  it('returns the session media_provider when set', () => {
    expect(
      resolveMediaProvider({ media_provider: 'custom_webrtc' })
    ).toBe('custom_webrtc')
    expect(resolveMediaProvider({ media_provider: 'livekit' })).toBe(
      'livekit'
    )
  })
})
