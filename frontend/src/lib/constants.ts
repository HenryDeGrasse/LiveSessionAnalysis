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

function parseNumberEnv(name: string, fallback: number): number {
  const raw = process.env[name]
  if (!raw) return fallback
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function parseBooleanEnv(name: string, fallback: boolean): boolean {
  const raw = process.env[name]
  if (!raw) return fallback
  if (raw === 'true') return true
  if (raw === 'false') return false
  return fallback
}

export const LOCAL_VIDEO_WIDTH = parseNumberEnv('NEXT_PUBLIC_VIDEO_WIDTH', 1920)
export const LOCAL_VIDEO_HEIGHT = parseNumberEnv('NEXT_PUBLIC_VIDEO_HEIGHT', 1080)
export const LOCAL_VIDEO_FRAME_RATE = parseNumberEnv('NEXT_PUBLIC_VIDEO_FRAME_RATE', 30)
export const LIVEKIT_ADAPTIVE_STREAM = parseBooleanEnv(
  'NEXT_PUBLIC_LIVEKIT_ADAPTIVE_STREAM',
  true
)
export const LIVEKIT_DYNACAST = parseBooleanEnv(
  'NEXT_PUBLIC_LIVEKIT_DYNACAST',
  true
)
/** Disable simulcast for 1:1 calls — all bitrate goes to a single high-quality layer. */
export const LIVEKIT_SIMULCAST = parseBooleanEnv(
  'NEXT_PUBLIC_LIVEKIT_SIMULCAST',
  false
)
/**
 * Video codec: 'h264' uses hardware encode/decode on most devices for better
 * quality-per-bit and higher sustained FPS.  'vp8' is the safest fallback.
 */
export const LIVEKIT_VIDEO_CODEC =
  process.env.NEXT_PUBLIC_LIVEKIT_VIDEO_CODEC || 'h264'
/**
 * Max video bitrate override in bps. 0 means use the resolution-based default.
 * For 1080p, 4_500_000 (4.5 Mbps) gives Zoom/Meet-class quality.
 */
export const LIVEKIT_VIDEO_MAX_BITRATE = parseNumberEnv(
  'NEXT_PUBLIC_LIVEKIT_VIDEO_MAX_BITRATE',
  0
)

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
