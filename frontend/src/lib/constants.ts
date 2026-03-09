export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'

export const ENABLE_WEBRTC_CALL_UI =
  process.env.NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI !== 'false'

export const LIVEKIT_URL =
  process.env.NEXT_PUBLIC_LIVEKIT_URL || ''

export const MEDIA_PROVIDER_OVERRIDE =
  process.env.NEXT_PUBLIC_MEDIA_PROVIDER_OVERRIDE || ''

const DEFAULT_ICE_SERVERS: RTCIceServer[] = [
  { urls: 'stun:stun.l.google.com:19302' },
]

function parseIceServers(): RTCIceServer[] {
  const raw = process.env.NEXT_PUBLIC_ICE_SERVERS
  if (!raw) return DEFAULT_ICE_SERVERS

  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed as RTCIceServer[]
    }
  } catch (error) {
    console.warn('Failed to parse NEXT_PUBLIC_ICE_SERVERS, using default STUN', error)
  }

  return DEFAULT_ICE_SERVERS
}

export const WEBRTC_ICE_SERVERS = parseIceServers()
