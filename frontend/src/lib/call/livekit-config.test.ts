import { describe, expect, it } from 'vitest'
import { VideoPresets } from 'livekit-client'
import { buildLiveKitConfig } from './livekit-config'

describe('buildLiveKitConfig', () => {
  it('uses h1080 encoding for 1920x1080 capture', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      adaptiveStream: false,
      dynacast: false,
    })

    expect(config.roomOptions.adaptiveStream).toBe(false)
    expect(config.roomOptions.dynacast).toBe(false)

    // Should use h1080 bitrate
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(
      VideoPresets.h1080.encoding.maxBitrate
    )
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(30)

    // Simulcast layers for 1080p: h540 + h216
    expect(config.videoPublishOptions.videoSimulcastLayers).toHaveLength(2)
    expect(config.videoPublishOptions.videoSimulcastLayers![0].width).toBe(
      VideoPresets.h540.width
    )
    expect(config.videoPublishOptions.videoSimulcastLayers![1].width).toBe(
      VideoPresets.h216.width
    )
  })

  it('uses h720 encoding for 1280x720 capture', () => {
    const config = buildLiveKitConfig({
      width: 1280,
      height: 720,
      frameRate: 30,
      adaptiveStream: true,
      dynacast: true,
    })

    expect(config.roomOptions.adaptiveStream).toBe(true)
    expect(config.roomOptions.dynacast).toBe(true)

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(
      VideoPresets.h720.encoding.maxBitrate
    )

    // Simulcast layers for 720p: h360 + h180
    expect(config.videoPublishOptions.videoSimulcastLayers).toHaveLength(2)
    expect(config.videoPublishOptions.videoSimulcastLayers![0].width).toBe(
      VideoPresets.h360.width
    )
  })

  it('uses h540 encoding for 960x540 capture', () => {
    const config = buildLiveKitConfig({
      width: 960,
      height: 540,
      frameRate: 24,
    })

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(
      VideoPresets.h540.encoding.maxBitrate
    )
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(24)
  })

  it('falls back to h720 for very small resolutions', () => {
    const config = buildLiveKitConfig({
      width: 320,
      height: 240,
      frameRate: 15,
    })

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(
      VideoPresets.h720.encoding.maxBitrate
    )
  })

  it('sets capture resolution in room options', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
    })

    expect(config.roomOptions.videoCaptureDefaults?.resolution).toEqual({
      width: 1920,
      height: 1080,
      frameRate: 30,
    })
  })

  it('sets publishDefaults on room options matching video publish options', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
    })

    expect(config.roomOptions.publishDefaults?.videoEncoding?.maxBitrate).toBe(
      VideoPresets.h1080.encoding.maxBitrate
    )
    expect(config.roomOptions.publishDefaults?.simulcast).toBe(true)
  })

  it('configures audio publish options with dtx and red', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
    })

    expect(config.audioPublishOptions.dtx).toBe(true)
    expect(config.audioPublishOptions.red).toBe(true)
  })
})
