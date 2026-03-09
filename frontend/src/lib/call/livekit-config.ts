import { VideoPresets, type RoomOptions, type TrackPublishOptions } from 'livekit-client'
import {
  LIVEKIT_ADAPTIVE_STREAM,
  LIVEKIT_DYNACAST,
  LOCAL_VIDEO_FRAME_RATE,
  LOCAL_VIDEO_HEIGHT,
  LOCAL_VIDEO_WIDTH,
} from '@/lib/constants'

/**
 * Pick the best matching VideoPreset encoding for the configured capture resolution.
 * Falls through from highest to lowest; defaults to h720 if nothing matches.
 */
function videoEncodingForResolution(width: number, height: number) {
  if (height >= 1080 && width >= 1920) return VideoPresets.h1080.encoding
  if (height >= 720 && width >= 1280) return VideoPresets.h720.encoding
  if (height >= 540 && width >= 960) return VideoPresets.h540.encoding
  if (height >= 360 && width >= 640) return VideoPresets.h360.encoding
  return VideoPresets.h720.encoding
}

/**
 * Simulcast layers below the primary encoding.
 * For 1080p primary we add h540 + h216; for 720p we add h360 + h180.
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
}): LiveKitRoomConfig {
  const width = overrides?.width ?? LOCAL_VIDEO_WIDTH
  const height = overrides?.height ?? LOCAL_VIDEO_HEIGHT
  const frameRate = overrides?.frameRate ?? LOCAL_VIDEO_FRAME_RATE
  const adaptiveStream = overrides?.adaptiveStream ?? LIVEKIT_ADAPTIVE_STREAM
  const dynacast = overrides?.dynacast ?? LIVEKIT_DYNACAST

  const encoding = videoEncodingForResolution(width, height)
  // Override maxFramerate to match capture
  const videoEncoding = { ...encoding, maxFramerate: frameRate }
  const simulcastLayers = simulcastLayersForResolution(height)

  const roomOptions: RoomOptions = {
    adaptiveStream,
    dynacast,
    videoCaptureDefaults: {
      resolution: { width, height, frameRate },
    },
    publishDefaults: {
      videoEncoding,
      videoSimulcastLayers: simulcastLayers,
      simulcast: true,
      // High-quality audio for tutoring
      dtx: true,
      red: true,
    },
  }

  const videoPublishOptions: TrackPublishOptions = {
    videoEncoding,
    videoSimulcastLayers: simulcastLayers,
    simulcast: true,
    source: 'camera' as any,
  }

  const audioPublishOptions: TrackPublishOptions = {
    dtx: true,
    red: true,
    source: 'microphone' as any,
  }

  return { roomOptions, videoPublishOptions, audioPublishOptions }
}
