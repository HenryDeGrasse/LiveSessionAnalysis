import { describe, expect, it } from 'vitest'
import { resolveMediaProvider } from '@/lib/call/provider'

describe('resolveMediaProvider', () => {
  it('defaults to custom_webrtc when session info is absent', () => {
    expect(resolveMediaProvider(null)).toBe('custom_webrtc')
  })

  it('uses the provider from session info when present', () => {
    expect(resolveMediaProvider({ media_provider: 'livekit' })).toBe('livekit')
    expect(resolveMediaProvider({ media_provider: 'custom_webrtc' })).toBe(
      'custom_webrtc'
    )
  })
})
