export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/**
 * Google OAuth client ID (public — safe to expose to the browser).
 * Required when the Google sign-in button is rendered on the client.
 */
export const GOOGLE_CLIENT_ID =
  process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ''

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
/**
 * Capture and publish frame rate for the local video track.
 * The default is 60fps for smooth, high-quality video during tutoring calls.
 *
 * NOTE: This is the *capture/publish* FPS, independent of backend analysis FPS.
 * The backend rate-limits analysis via `should_process_video_frame` (default 3 fps),
 * so increasing capture FPS does not increase CPU load on the analysis server —
 * it only improves call quality for participants.
 */
export const LOCAL_VIDEO_FRAME_RATE = parseNumberEnv('NEXT_PUBLIC_VIDEO_FRAME_RATE', 60)
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
 * For 1080p60, the default tier is 6_000_000 (6 Mbps); lower resolutions use
 * their own tiers in livekit-config.ts.
 */
export const LIVEKIT_VIDEO_MAX_BITRATE = parseNumberEnv(
  'NEXT_PUBLIC_LIVEKIT_VIDEO_MAX_BITRATE',
  0
)

// Legacy WEBRTC_ICE_SERVERS removed — LiveKit handles all media transport.
