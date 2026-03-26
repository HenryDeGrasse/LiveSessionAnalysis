'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  LOCAL_VIDEO_FRAME_RATE,
  LOCAL_VIDEO_HEIGHT,
  LOCAL_VIDEO_WIDTH,
} from '@/lib/constants'

interface UseMediaStreamOptions {
  video?: boolean
  audio?: boolean
}

interface TrackReplacementResult {
  previousTrack: MediaStreamTrack | null
  newTrack: MediaStreamTrack
}

export function useMediaStream(
  options: UseMediaStreamOptions = { video: true, audio: true }
) {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hasConsented, setHasConsented] = useState(false)
  const [isAudioEnabled, setIsAudioEnabled] = useState(Boolean(options.audio))
  const [isVideoEnabled, setIsVideoEnabled] = useState(Boolean(options.video))
  const [audioInputs, setAudioInputs] = useState<MediaDeviceInfo[]>([])
  const [videoInputs, setVideoInputs] = useState<MediaDeviceInfo[]>([])
  const [selectedAudioInputId, setSelectedAudioInputId] = useState('')
  const [selectedVideoInputId, setSelectedVideoInputId] = useState('')
  const streamRef = useRef<MediaStream | null>(null)

  const refreshDevices = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      setAudioInputs(devices.filter((device) => device.kind === 'audioinput'))
      setVideoInputs(devices.filter((device) => device.kind === 'videoinput'))
    } catch {
      // ignore enumerate failures until permissions are granted
    }
  }, [])

  const syncSelectedDeviceIds = useCallback((mediaStream: MediaStream) => {
    const audioTrack = mediaStream.getAudioTracks()[0]
    const videoTrack = mediaStream.getVideoTracks()[0]
    const audioDeviceId = audioTrack?.getSettings?.().deviceId
    const videoDeviceId = videoTrack?.getSettings?.().deviceId

    if (typeof audioDeviceId === 'string' && audioDeviceId) {
      setSelectedAudioInputId(audioDeviceId)
    }
    if (typeof videoDeviceId === 'string' && videoDeviceId) {
      setSelectedVideoInputId(videoDeviceId)
    }
  }, [])

  const applyStream = useCallback((mediaStream: MediaStream) => {
    streamRef.current = mediaStream
    setStream(mediaStream)
    setHasConsented(true)
    setIsAudioEnabled(mediaStream.getAudioTracks().some((track) => track.enabled))
    setIsVideoEnabled(mediaStream.getVideoTracks().some((track) => track.enabled))
    setError(null)
    syncSelectedDeviceIds(mediaStream)
    void refreshDevices()
  }, [refreshDevices, syncSelectedDeviceIds])

  const buildAudioConstraints = useCallback(
    (deviceId?: string): MediaTrackConstraints => ({
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      // Avoid forcing a specific sample rate / channel count here.
      // Some browsers + devices (especially Bluetooth headsets / Safari)
      // can return a "working" track that produces no usable audio when
      // constrained to 16kHz mono at capture time.
      //
      // Our analytics pipeline already resamples to 16kHz mono later, so
      // it is safer to capture at the device/browser native settings.
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    }),
    []
  )

  const buildVideoConstraints = useCallback(
    (deviceId?: string): MediaTrackConstraints => ({
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      width: { ideal: LOCAL_VIDEO_WIDTH },
      height: { ideal: LOCAL_VIDEO_HEIGHT },
      frameRate: { ideal: LOCAL_VIDEO_FRAME_RATE, max: LOCAL_VIDEO_FRAME_RATE },
    }),
    []
  )

  const requestAccess = useCallback(async (overrides?: {
    audioDeviceId?: string
    videoDeviceId?: string
  }) => {
    try {
      const audioDeviceId = overrides?.audioDeviceId || selectedAudioInputId
      const videoDeviceId = overrides?.videoDeviceId || selectedVideoInputId
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: options.video
          ? buildVideoConstraints(videoDeviceId)
          : false,
        audio: options.audio
          ? buildAudioConstraints(audioDeviceId)
          : false,
      })
      const previousStream = streamRef.current
      applyStream(mediaStream)
      previousStream?.getTracks().forEach((track) => track.stop())
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Failed to access camera/microphone'
      )
    }
  }, [applyStream, buildAudioConstraints, buildVideoConstraints, options.video, options.audio, selectedAudioInputId, selectedVideoInputId])

  const replaceTrack = useCallback(
    (kind: 'audio' | 'video', nextTrack: MediaStreamTrack): TrackReplacementResult => {
      const currentStream = streamRef.current
      const previousTrack =
        kind === 'audio'
          ? currentStream?.getAudioTracks()[0] ?? null
          : currentStream?.getVideoTracks()[0] ?? null

      nextTrack.enabled = kind === 'audio' ? isAudioEnabled : isVideoEnabled

      const preservedTracks = (currentStream?.getTracks() ?? []).filter(
        (track) => track.kind !== kind
      )
      const nextStream = new MediaStream([...preservedTracks, nextTrack])
      applyStream(nextStream)
      previousTrack?.stop()

      return { previousTrack, newTrack: nextTrack }
    },
    [applyStream, isAudioEnabled, isVideoEnabled]
  )

  const selectAudioInput = useCallback(async (deviceId: string) => {
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: buildAudioConstraints(deviceId),
      video: false,
    })
    const nextTrack = mediaStream.getAudioTracks()[0]
    if (!nextTrack) {
      throw new Error('Selected microphone did not provide an audio track')
    }
    setSelectedAudioInputId(deviceId)
    return replaceTrack('audio', nextTrack)
  }, [buildAudioConstraints, replaceTrack])

  const selectVideoInput = useCallback(async (deviceId: string) => {
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: buildVideoConstraints(deviceId),
    })
    const nextTrack = mediaStream.getVideoTracks()[0]
    if (!nextTrack) {
      throw new Error('Selected camera did not provide a video track')
    }
    setSelectedVideoInputId(deviceId)
    return replaceTrack('video', nextTrack)
  }, [buildVideoConstraints, replaceTrack])

  const toggleAudio = useCallback(() => {
    const tracks = streamRef.current?.getAudioTracks() || []
    if (tracks.length === 0) return

    const nextEnabled = !tracks.some((track) => track.enabled)
    tracks.forEach((track) => {
      track.enabled = nextEnabled
    })
    setIsAudioEnabled(nextEnabled)
  }, [])

  const toggleVideo = useCallback(() => {
    const tracks = streamRef.current?.getVideoTracks() || []
    if (tracks.length === 0) return

    const nextEnabled = !tracks.some((track) => track.enabled)
    tracks.forEach((track) => {
      track.enabled = nextEnabled
    })
    setIsVideoEnabled(nextEnabled)
  }, [])

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
      setStream(null)
      setIsAudioEnabled(false)
      setIsVideoEnabled(false)
    }
  }, [])

  useEffect(() => {
    void refreshDevices()

    const onDeviceChange = () => {
      void refreshDevices()
    }
    navigator.mediaDevices?.addEventListener?.('devicechange', onDeviceChange)

    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', onDeviceChange)
      stopStream()
    }
  }, [refreshDevices, stopStream])

  return {
    stream,
    error,
    hasConsented,
    isAudioEnabled,
    isVideoEnabled,
    audioInputs,
    videoInputs,
    selectedAudioInputId,
    selectedVideoInputId,
    refreshDevices,
    requestAccess,
    selectAudioInput,
    selectVideoInput,
    toggleAudio,
    toggleVideo,
    stopStream,
  }
}
