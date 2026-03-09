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

export function useMediaStream(
  options: UseMediaStreamOptions = { video: true, audio: true }
) {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hasConsented, setHasConsented] = useState(false)
  const [isAudioEnabled, setIsAudioEnabled] = useState(Boolean(options.audio))
  const [isVideoEnabled, setIsVideoEnabled] = useState(Boolean(options.video))
  const streamRef = useRef<MediaStream | null>(null)

  const requestAccess = useCallback(async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: options.video
          ? {
              width: { ideal: LOCAL_VIDEO_WIDTH },
              height: { ideal: LOCAL_VIDEO_HEIGHT },
              frameRate: { ideal: LOCAL_VIDEO_FRAME_RATE, max: LOCAL_VIDEO_FRAME_RATE },
            }
          : false,
        audio: options.audio
          ? { sampleRate: 16000, channelCount: 1, echoCancellation: true }
          : false,
      })
      streamRef.current = mediaStream
      setStream(mediaStream)
      setHasConsented(true)
      setIsAudioEnabled(mediaStream.getAudioTracks().some((track) => track.enabled))
      setIsVideoEnabled(mediaStream.getVideoTracks().some((track) => track.enabled))
      setError(null)
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Failed to access camera/microphone'
      )
    }
  }, [options.video, options.audio])

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
    return () => {
      stopStream()
    }
  }, [stopStream])

  return {
    stream,
    error,
    hasConsented,
    isAudioEnabled,
    isVideoEnabled,
    requestAccess,
    toggleAudio,
    toggleVideo,
    stopStream,
  }
}
