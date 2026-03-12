import { describe, expect, it } from 'vitest'
import { VideoPresets } from 'livekit-client'
import { buildLiveKitConfig } from './livekit-config'

describe('buildLiveKitConfig', () => {
  // ── 60fps default behaviour ────────────────────────────────────────────
  it('uses 60fps and the default bitrate tier with no overrides', () => {
    const config = buildLiveKitConfig()

    expect(config.roomOptions.videoCaptureDefaults?.resolution).toEqual({
      width: 1920,
      height: 1080,
      frameRate: 60,
    })
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(6_000_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(60)
    expect(config.roomOptions.publishDefaults?.videoEncoding?.maxFramerate).toBe(60)
  })

  it('uses 6 Mbps encoding for 1920x1080 at 60fps (default tier)', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 60,
      adaptiveStream: false,
      dynacast: false,
      simulcast: false,
    })

    expect(config.roomOptions.adaptiveStream).toBe(false)
    expect(config.roomOptions.dynacast).toBe(false)

    // 60fps 1080p needs ~1.5x the bandwidth of 30fps → 6 Mbps tier
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(6_000_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(60)
  })

  it('propagates 60fps frameRate into room capture defaults', () => {
    const config = buildLiveKitConfig({
      width: 1920,
      height: 1080,
      frameRate: 60,
    })

    expect(config.roomOptions.videoCaptureDefaults?.resolution?.frameRate).toBe(60)
    expect(config.roomOptions.publishDefaults?.videoEncoding?.maxFramerate).toBe(60)
  })

  it('uses 6 Mbps encoding for 1920x1080 capture (higher than 30fps LK default)', () => {
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

    // 30fps at 1080p is within the 6 Mbps tier (comfortable headroom)
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(6_000_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(30)
  })

  it('uses 3.5 Mbps encoding for 1280x720 capture', () => {
    const config = buildLiveKitConfig({
      width: 1280,
      height: 720,
      frameRate: 60,
      adaptiveStream: true,
      dynacast: true,
      simulcast: false,
    })

    expect(config.roomOptions.adaptiveStream).toBe(true)
    expect(config.roomOptions.dynacast).toBe(true)
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(3_500_000)
    expect(config.videoPublishOptions.videoEncoding?.maxFramerate).toBe(60)
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

  it('falls back to 3.5 Mbps (720p tier) for very small resolutions', () => {
    const config = buildLiveKitConfig({
      width: 320,
      height: 240,
      frameRate: 15,
    })

    // The else-branch falls through to the 720p tier
    expect(config.videoPublishOptions.videoEncoding?.maxBitrate).toBe(3_500_000)
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
