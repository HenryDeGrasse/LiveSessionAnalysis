import { VideoPresets, type RoomOptions, type TrackPublishOptions, type VideoCodec } from 'livekit-client'
import {
  LIVEKIT_ADAPTIVE_STREAM,
  LIVEKIT_DYNACAST,
  LIVEKIT_SIMULCAST,
  LIVEKIT_VIDEO_CODEC,
  LIVEKIT_VIDEO_MAX_BITRATE,
  LOCAL_VIDEO_FRAME_RATE,
  LOCAL_VIDEO_HEIGHT,
  LOCAL_VIDEO_WIDTH,
} from '@/lib/constants'

// ── Bitrate tiers (bps) ────────────────────────────────────────────────
// Sized for 60fps capture (default).  60fps at a given resolution needs
// ~1.5x the bitrate of 30fps to maintain comparable quality per-frame.
// At 30fps these tiers are still comfortable headroom over 30fps requirements.
const BITRATE_1080 = 6_000_000 // 6 Mbps  — 60fps 1080p  (was 4.5 Mbps @ 30fps)
const BITRATE_720 = 3_500_000 // 3.5 Mbps — 60fps 720p   (was 2.5 Mbps @ 30fps)
const BITRATE_540 = 1_200_000 // 1.2 Mbps — unchanged (540p/30fps acceptable)
const BITRATE_360 = 600_000 //   600 Kbps — unchanged

/**
 * Pick a high-quality video encoding for the configured capture resolution.
 * If LIVEKIT_VIDEO_MAX_BITRATE is set, it overrides the tier-based default.
 */
function videoEncodingForResolution(
  width: number,
  height: number,
  frameRate: number,
  bitrateOverride: number
) {
  let maxBitrate: number
  if (bitrateOverride > 0) {
    maxBitrate = bitrateOverride
  } else if (height >= 1080 && width >= 1920) {
    maxBitrate = BITRATE_1080
  } else if (height >= 720 && width >= 1280) {
    maxBitrate = BITRATE_720
  } else if (height >= 540 && width >= 960) {
    maxBitrate = BITRATE_540
  } else if (height >= 360 && width >= 640) {
    maxBitrate = BITRATE_360
  } else {
    maxBitrate = BITRATE_720
  }

  return { maxBitrate, maxFramerate: frameRate }
}

/**
 * Simulcast layers below the primary encoding.
 * Only used when simulcast is enabled (typically for 1:N scenarios).
 */
function simulcastLayersForResolution(height: number) {
  if (height >= 1080) return [VideoPresets.h540, VideoPresets.h216]
  if (height >= 720) return [VideoPresets.h360, VideoPresets.h180]
  return [VideoPresets.h180]
}

export interface LiveKitRoomConfig {
  roomOptions: RoomOptions
  videoPublishOptions: TrackPublishOptions
  audioPublishOptions: TrackPublishOptions
}

export function buildLiveKitConfig(overrides?: {
  width?: number
  height?: number
  frameRate?: number
  adaptiveStream?: boolean
  dynacast?: boolean
  simulcast?: boolean
  videoCodec?: string
  maxBitrate?: number
}): LiveKitRoomConfig {
  const width = overrides?.width ?? LOCAL_VIDEO_WIDTH
  const height = overrides?.height ?? LOCAL_VIDEO_HEIGHT
  const frameRate = overrides?.frameRate ?? LOCAL_VIDEO_FRAME_RATE
  const adaptiveStream = overrides?.adaptiveStream ?? LIVEKIT_ADAPTIVE_STREAM
  const dynacast = overrides?.dynacast ?? LIVEKIT_DYNACAST
  const simulcast = overrides?.simulcast ?? LIVEKIT_SIMULCAST
  const videoCodec = (overrides?.videoCodec ?? LIVEKIT_VIDEO_CODEC) as VideoCodec
  const bitrateOverride = overrides?.maxBitrate ?? LIVEKIT_VIDEO_MAX_BITRATE

  const videoEncoding = videoEncodingForResolution(width, height, frameRate, bitrateOverride)
  const simulcastLayers = simulcast ? simulcastLayersForResolution(height) : []

  const roomOptions: RoomOptions = {
    adaptiveStream,
    dynacast,
    videoCaptureDefaults: {
      resolution: { width, height, frameRate },
    },
    publishDefaults: {
      videoEncoding,
      videoCodec,
      simulcast,
      ...(simulcast ? { videoSimulcastLayers: simulcastLayers } : {}),
      // High-quality audio for tutoring
      dtx: true,
      red: true,
    },
  }

  const videoPublishOptions: TrackPublishOptions = {
    videoEncoding,
    videoCodec,
    simulcast,
    ...(simulcast ? { videoSimulcastLayers: simulcastLayers } : {}),
    source: 'camera' as any,
  }

  const audioPublishOptions: TrackPublishOptions = {
    dtx: true,
    red: true,
    source: 'microphone' as any,
  }

  return { roomOptions, videoPublishOptions, audioPublishOptions }
}
