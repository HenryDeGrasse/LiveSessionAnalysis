import { describe, expect, it } from 'vitest'
import { VideoPresets } from 'livekit-client'
import { buildLiveKitConfig } from './livekit-config'

describe('buildLiveKitConfig', () => {
  it('uses 4.5 Mbps encoding for 1920x1080 capture (higher than LK default)', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      adaptiveStream: false,
      dynacast: false,
      simulcast: false,
    })

    expect(config.roomOptions.adaptiveStream).toBe(false)
    expect(config.roomOptions.dynacast).toBe(false)

    // Should use our higher 4.5 Mbps tier, not LK's default 3 Mbps
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(4_500_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(30)
  })

  it('uses 2.5 Mbps encoding for 1280x720 capture', () => {
    const config = buildLiveKitConfig({
      width: 1280,
      height: 720,
      frameRate: 30,
      adaptiveStream: true,
      dynacast: true,
      simulcast: false,
    })

    expect(config.roomOptions.adaptiveStream).toBe(true)
    expect(config.roomOptions.dynacast).toBe(true)
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(2_500_000)
  })

  it('uses 1.2 Mbps encoding for 960x540 capture', () => {
    const config = buildLiveKitConfig({
      width: 960,
      height: 540,
      frameRate: 24,
    })

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(1_200_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(24)
  })

  it('falls back to 2.5 Mbps (720p tier) for very small resolutions', () => {
    const config = buildLiveKitConfig({
      width: 320,
      height: 240,
      frameRate: 15,
    })

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(2_500_000)
  })

  it('disables simulcast by default for 1:1 calls', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      simulcast: false,
    })

    expect(config.videoPublishOptions.simulcast).toBe(false)
    expect(config.videoPublishOptions.videoSimulcastLayers).toBeUndefined()
    expect(config.roomOptions.publishDefaults?.simulcast).toBe(false)
    expect(config.roomOptions.publishDefaults?.videoSimulcastLayers).toBeUndefined()
  })

  it('includes simulcast layers when simulcast is enabled', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      simulcast: true,
    })

    expect(config.videoPublishOptions.simulcast).toBe(true)
    expect(config.videoPublishOptions.videoSimulcastLayers).toHaveLength(2)
    expect(config.videoPublishOptions.videoSimulcastLayers![0].width).toBe(
      VideoPresets.h540.width
    )
    expect(config.videoPublishOptions.videoSimulcastLayers![1].width).toBe(
      VideoPresets.h216.width
    )
  })

  it('defaults to h264 video codec', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
    })

    expect(config.videoPublishOptions.videoCodec).toBe('h264')
    expect(config.roomOptions.publishDefaults?.videoCodec).toBe('h264')
  })

  it('allows overriding video codec', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      videoCodec: 'vp8',
    })

    expect(config.videoPublishOptions.videoCodec).toBe('vp8')
    expect(config.roomOptions.publishDefaults?.videoCodec).toBe('vp8')
  })

  it('allows overriding max bitrate', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 30,
      maxBitrate: 6_000_000,
    })

    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(6_000_000)
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
