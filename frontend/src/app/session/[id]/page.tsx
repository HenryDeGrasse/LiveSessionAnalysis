'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useMediaStream } from '@/hooks/useMediaStream'
import { useMetrics } from '@/hooks/useMetrics'
import { useNudges } from '@/hooks/useNudges'
import { useCallTransport } from '@/hooks/useCallTransport'
import { API_URL, ENABLE_WEBRTC_CALL_UI } from '@/lib/constants'
import { resolveMediaProvider } from '@/lib/call/provider'
import { encodeVideoFrame, encodeAudioChunk } from '@/lib/frameEncoder'
import type {
  MetricsSnapshot,
  Nudge,
  SessionInfo,
  WSMessage,
  WebRTCSignalData,
} from '@/lib/types'

type SessionRole = 'tutor' | 'student'

type AudioContextCtor = typeof AudioContext

declare global {
  interface Window {
    webkitAudioContext?: AudioContextCtor
  }
}

function resampleAudio(
  input: Float32Array,
  sourceRate: number,
  targetRate: number
): Float32Array {
  if (input.length === 0 || sourceRate === targetRate) {
    return input
  }

  const ratio = sourceRate / targetRate
  const outputLength = Math.max(1, Math.round(input.length / ratio))
  const output = new Float32Array(outputLength)

  for (let i = 0; i < outputLength; i++) {
    const position = i * ratio
    const leftIndex = Math.floor(position)
    const rightIndex = Math.min(leftIndex + 1, input.length - 1)
    const blend = position - leftIndex
    output[i] = input[leftIndex] * (1 - blend) + input[rightIndex] * blend
  }

  return output
}

function floatToPcm16(input: ArrayLike<number>): Int16Array {
  const pcm = new Int16Array(input.length)

  for (let i = 0; i < input.length; i++) {
    const sample = Math.max(-1, Math.min(1, input[i]))
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }

  return pcm
}

function formatAttentionStateLabel(
  state: MetricsSnapshot['student']['attention_state']
) {
  switch (state) {
    case 'FACE_MISSING':
      return 'Face missing'
    case 'LOW_CONFIDENCE':
      return 'Low confidence'
    case 'CAMERA_FACING':
      return 'Camera-facing'
    case 'SCREEN_ENGAGED':
      return 'Screen-engaged'
    case 'DOWN_ENGAGED':
      return 'Down-engaged'
    case 'OFF_TASK_AWAY':
      return 'Away'
  }
}

function attentionPillClasses(
  state: MetricsSnapshot['student']['attention_state']
) {
  switch (state) {
    case 'CAMERA_FACING':
      return 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100 shadow-[0_0_22px_rgba(16,185,129,0.18)]'
    case 'SCREEN_ENGAGED':
      return 'border-sky-400/40 bg-sky-500/10 text-sky-100 shadow-[0_0_22px_rgba(56,189,248,0.16)]'
    case 'DOWN_ENGAGED':
      return 'border-amber-400/40 bg-amber-500/10 text-amber-100 shadow-[0_0_22px_rgba(245,158,11,0.16)]'
    case 'OFF_TASK_AWAY':
    case 'FACE_MISSING':
      return 'border-rose-400/40 bg-rose-500/10 text-rose-100 shadow-[0_0_22px_rgba(244,63,94,0.18)]'
    case 'LOW_CONFIDENCE':
      return 'border-gray-400/30 bg-gray-500/10 text-gray-100 shadow-[0_0_18px_rgba(148,163,184,0.12)]'
  }
}

function flowSummary(metrics: MetricsSnapshot) {
  if (metrics.session.active_overlap_state === 'hard') {
    return {
      label: 'Turn flow',
      value: 'Interrupting',
      className:
        'border-rose-400/40 bg-rose-500/10 text-rose-100 shadow-[0_0_22px_rgba(244,63,94,0.18)]',
    }
  }

  if (metrics.session.active_overlap_state !== 'none') {
    return {
      label: 'Turn flow',
      value: 'Overlapping',
      className:
        'border-orange-400/40 bg-orange-500/10 text-orange-100 shadow-[0_0_22px_rgba(249,115,22,0.18)]',
    }
  }

  if (metrics.session.tutor_monologue_duration_current >= 20) {
    return {
      label: 'Turn flow',
      value: 'Tutor holding floor',
      className:
        'border-amber-400/40 bg-amber-500/10 text-amber-100 shadow-[0_0_22px_rgba(245,158,11,0.16)]',
    }
  }

  if (metrics.session.mutual_silence_duration_current >= 6) {
    return {
      label: 'Turn flow',
      value: 'Long pause',
      className:
        'border-gray-400/30 bg-gray-500/10 text-gray-100 shadow-[0_0_18px_rgba(148,163,184,0.12)]',
    }
  }

  return {
    label: 'Turn flow',
    value: 'Smooth',
    className:
      'border-emerald-400/40 bg-emerald-500/10 text-emerald-100 shadow-[0_0_22px_rgba(16,185,129,0.18)]',
  }
}

function talkBalanceSummary(metrics: MetricsSnapshot) {
  const tutorShare = metrics.session.recent_tutor_talk_percent

  if (tutorShare >= 0.78) {
    return {
      label: 'Talk balance',
      value: 'Tutor-leading',
      className:
        'border-amber-400/40 bg-amber-500/10 text-amber-100 shadow-[0_0_22px_rgba(245,158,11,0.16)]',
    }
  }

  if (tutorShare <= 0.22) {
    return {
      label: 'Talk balance',
      value: 'Student-leading',
      className:
        'border-sky-400/40 bg-sky-500/10 text-sky-100 shadow-[0_0_22px_rgba(56,189,248,0.16)]',
    }
  }

  return {
    label: 'Talk balance',
    value: 'Balanced',
    className:
      'border-emerald-400/40 bg-emerald-500/10 text-emerald-100 shadow-[0_0_22px_rgba(16,185,129,0.18)]',
  }
}

function callStatusLabel(status: string) {
  switch (status) {
    case 'connected':
      return 'Connected'
    case 'connecting':
      return 'Connecting media'
    case 'reconnecting':
      return 'Reconnecting'
    case 'waiting_for_participant':
      return 'Waiting for participant'
    default:
      return 'Call disabled'
  }
}

function callStatusClasses(status: string) {
  switch (status) {
    case 'connected':
      return 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
    case 'connecting':
      return 'border-sky-400/40 bg-sky-500/10 text-sky-100'
    case 'reconnecting':
      return 'border-amber-400/40 bg-amber-500/10 text-amber-100'
    case 'waiting_for_participant':
      return 'border-gray-400/30 bg-gray-500/10 text-gray-100'
    default:
      return 'border-gray-400/30 bg-gray-500/10 text-gray-100'
  }
}

export default function SessionPage() {
  const routeParams = useParams<{ id: string }>()
  const router = useRouter()
  const sessionId = routeParams.id
  const searchParams = useSearchParams()
  const token = searchParams.get('token') || ''

  const [role, setRole] = useState<SessionRole | null>(null)
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)
  const [sessionInfoLoaded, setSessionInfoLoaded] = useState(false)
  const [showConsent, setShowConsent] = useState(true)
  const [sessionEnded, setSessionEnded] = useState(false)
  const [peerDisconnected, setPeerDisconnected] = useState(false)
  const [endingSession, setEndingSession] = useState(false)
  const [endSessionError, setEndSessionError] = useState<string | null>(null)
  const [debugEvents, setDebugEvents] = useState<Array<{ at: string; message: string }>>([])
  const [showCoachDebug, setShowCoachDebug] = useState(
    searchParams.get('debug') === '1'
  )

  const videoRef = useRef<HTMLVideoElement>(null)
  const remoteVideoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const frameIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const targetFpsRef = useRef<number>(3)
  const audioContextRef = useRef<AudioContext | null>(null)
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const audioProcessorRef = useRef<ScriptProcessorNode | null>(null)
  const audioSampleBufferRef = useRef<number[]>([])
  const peerHandlersReadyRef = useRef(false)
  const pendingPeerEventsRef = useRef<
    Array<
      | { type: 'participant_ready' }
      | { type: 'participant_disconnected' }
      | { type: 'participant_reconnected' }
      | { type: 'webrtc_signal'; data: WebRTCSignalData }
      | { type: 'session_end' }
    >
  >([])
  const peerHandlersRef = useRef({
    handleSignal: async (_signal: WebRTCSignalData) => {},
    handleParticipantReady: async () => {},
    handleParticipantDisconnected: () => {},
    handleParticipantReconnected: async () => {},
    closeConnection: (_reason: string) => {},
  })

  const {
    stream,
    error: mediaError,
    requestAccess,
    isAudioEnabled,
    isVideoEnabled,
    toggleAudio,
    toggleVideo,
    stopStream,
  } = useMediaStream()
  const { currentMetrics, metricsHistory, handleMetrics } = useMetrics()
  const {
    nudges,
    nudgeHistory,
    nudgesEnabled,
    handleNudge,
    dismissNudge,
    disableAllNudges,
    enableAllNudges,
  } = useNudges()

  const appendDebugEvent = useCallback((message: string) => {
    const at = new Date().toLocaleTimeString()
    setDebugEvents((prev) => [...prev.slice(-24), { at, message }])
  }, [])

  const queuePeerEvent = useCallback(
    (
      event:
        | { type: 'participant_ready' }
        | { type: 'participant_disconnected' }
        | { type: 'participant_reconnected' }
        | { type: 'webrtc_signal'; data: WebRTCSignalData }
        | { type: 'session_end' }
    ) => {
      pendingPeerEventsRef.current.push(event)
    },
    []
  )

  const flushPendingPeerEvents = useCallback(async () => {
    if (!peerHandlersReadyRef.current || pendingPeerEventsRef.current.length === 0) {
      return
    }

    const queued = [...pendingPeerEventsRef.current]
    pendingPeerEventsRef.current = []

    for (const event of queued) {
      switch (event.type) {
        case 'participant_ready':
          await peerHandlersRef.current.handleParticipantReady()
          break
        case 'participant_disconnected':
          peerHandlersRef.current.handleParticipantDisconnected()
          break
        case 'participant_reconnected':
          await peerHandlersRef.current.handleParticipantReconnected()
          break
        case 'webrtc_signal':
          await peerHandlersRef.current.handleSignal(event.data)
          break
        case 'session_end':
          peerHandlersRef.current.closeConnection('session ended')
          break
      }
    }
  }, [])

  useEffect(() => {
    if (searchParams.get('debug') === '1') {
      setShowCoachDebug(true)
    }
  }, [searchParams])

  useEffect(() => {
    if (!sessionId || !token) return

    fetch(
      `${API_URL}/api/sessions/${sessionId}/info?token=${encodeURIComponent(token)}`
    )
      .then((res) => res.json())
      .then((data: SessionInfo) => {
        setSessionInfo(data)
        if (data.role === 'tutor' || data.role === 'student') {
          setRole(data.role)
          appendDebugEvent(
            `session info loaded (${data.role}, provider=${data.media_provider})`
          )

          const remoteConnected =
            data.role === 'tutor' ? data.student_connected : data.tutor_connected
          if (ENABLE_WEBRTC_CALL_UI && remoteConnected && !data.ended) {
            if (peerHandlersReadyRef.current) {
              void peerHandlersRef.current.handleParticipantReady()
            } else {
              queuePeerEvent({ type: 'participant_ready' })
            }
          }
        }
        if (data.ended) {
          setSessionEnded(true)
        }
      })
      .catch(() => {
        // ignore role lookup failures; websocket still enforces auth
      })
      .finally(() => {
        setSessionInfoLoaded(true)
      })
  }, [sessionId, token, appendDebugEvent, queuePeerEvent])

  const onMessage = useCallback(
    (message: WSMessage) => {
      switch (message.type) {
        case 'metrics': {
          setRole('tutor')
          const metrics = message.data as MetricsSnapshot
          handleMetrics(metrics)
          appendDebugEvent(
            `metrics: attention=${metrics.student.attention_state} talk=${(metrics.tutor.talk_time_percent * 100).toFixed(0)}/${(metrics.student.talk_time_percent * 100).toFixed(0)} silence=${metrics.session.silence_duration_current.toFixed(0)}s int=${metrics.session.interruption_count}`
          )
          // Adapt client-side capture FPS to match backend target
          const newFps = metrics.target_fps
          if (newFps && newFps !== targetFpsRef.current && newFps >= 1 && newFps <= 10) {
            targetFpsRef.current = newFps
            // Restart frame interval with new FPS
            if (frameIntervalRef.current) {
              clearInterval(frameIntervalRef.current)
              frameIntervalRef.current = null
            }
          }
          break
        }
        case 'nudge':
          setRole('tutor')
          handleNudge(message.data as Nudge)
          appendDebugEvent(`nudge: ${(message.data as Nudge).nudge_type}`)
          break
        case 'session_end':
          setSessionEnded(true)
          setPeerDisconnected(false)
          if (peerHandlersReadyRef.current) {
            peerHandlersRef.current.closeConnection('session ended')
          } else {
            queuePeerEvent({ type: 'session_end' })
          }
          appendDebugEvent('session_end received')
          break
        case 'participant_ready':
          setPeerDisconnected(false)
          if (peerHandlersReadyRef.current) {
            void peerHandlersRef.current.handleParticipantReady()
          } else {
            queuePeerEvent({ type: 'participant_ready' })
          }
          appendDebugEvent('participant_ready received')
          break
        case 'participant_disconnected':
          setPeerDisconnected(true)
          if (peerHandlersReadyRef.current) {
            peerHandlersRef.current.handleParticipantDisconnected()
          } else {
            queuePeerEvent({ type: 'participant_disconnected' })
          }
          appendDebugEvent('participant_disconnected received')
          break
        case 'participant_reconnected':
          setPeerDisconnected(false)
          if (peerHandlersReadyRef.current) {
            void peerHandlersRef.current.handleParticipantReconnected()
          } else {
            queuePeerEvent({ type: 'participant_reconnected' })
          }
          appendDebugEvent('participant_reconnected received')
          break
        case 'webrtc_signal':
          if (peerHandlersReadyRef.current) {
            void peerHandlersRef.current.handleSignal(message.data as WebRTCSignalData)
          } else {
            queuePeerEvent({
              type: 'webrtc_signal',
              data: message.data as WebRTCSignalData,
            })
          }
          appendDebugEvent(
            `webrtc_signal: ${(message.data as WebRTCSignalData).signal_type} from ${(message.data as WebRTCSignalData).from_role}`
          )
          break
      }
    },
    [appendDebugEvent, handleMetrics, handleNudge, queuePeerEvent]
  )

  const { connected, error: wsError, sendBinary, sendJson } = useWebSocket({
    sessionId,
    token,
    onMessage,
  })

  const sendWebRTCSignal = useCallback(
    (signal: {
      signal_type: 'offer' | 'answer' | 'ice_candidate'
      payload: Record<string, unknown>
    }) => {
      sendJson({
        type: 'webrtc_signal',
        data: signal,
      })
    },
    [sendJson]
  )

  const mediaProvider = resolveMediaProvider(sessionInfo)

  const {
    remoteStream,
    remoteTrackCount,
    hasRemoteVideo,
    hasRemoteAudio,
    callStatus,
    connectionState,
    iceConnectionState,
    iceGatheringState,
    signalingState,
    error: peerError,
    handleSignal,
    handleParticipantReady,
    handleParticipantDisconnected,
    handleParticipantReconnected,
    closeConnection,
  } = useCallTransport({
    provider: mediaProvider,
    enabled: ENABLE_WEBRTC_CALL_UI && !sessionEnded,
    role,
    localStream: stream,
    sessionId,
    sessionToken: token,
    sendSignal: sendWebRTCSignal,
    onDebugEvent: appendDebugEvent,
  })

  useEffect(() => {
    peerHandlersRef.current = {
      handleSignal,
      handleParticipantReady,
      handleParticipantDisconnected,
      handleParticipantReconnected,
      closeConnection,
    }
    peerHandlersReadyRef.current = true
    void flushPendingPeerEvents()

    return () => {
      peerHandlersReadyRef.current = false
    }
  }, [
    closeConnection,
    flushPendingPeerEvents,
    handleParticipantDisconnected,
    handleParticipantReady,
    handleParticipantReconnected,
    handleSignal,
  ])

  useEffect(() => {
    if (!sessionId || !token) return
    appendDebugEvent(`websocket ${connected ? 'connected' : 'disconnected'}`)
  }, [appendDebugEvent, connected, sessionId, token])

  useEffect(() => {
    if (wsError) {
      appendDebugEvent(`websocket error: ${wsError}`)
    }
  }, [appendDebugEvent, wsError])

  useEffect(() => {
    if (mediaError) {
      appendDebugEvent(`media error: ${mediaError}`)
    }
  }, [appendDebugEvent, mediaError])

  useEffect(() => {
    if (peerError) {
      appendDebugEvent(`webrtc error: ${peerError}`)
    }
  }, [appendDebugEvent, peerError])

  useEffect(() => {
    if (remoteVideoRef.current) {
      remoteVideoRef.current.srcObject = remoteStream
      if (remoteStream) {
        void remoteVideoRef.current.play().catch(() => {
          // ignore autoplay issues during early setup
        })
      }
    }
  }, [remoteStream])

  useEffect(() => {
    if (!connected) return
    sendJson({
      type: 'client_status',
      data: {
        audio_muted: !isAudioEnabled,
        video_enabled: isVideoEnabled,
        tab_hidden: typeof document !== 'undefined' ? document.hidden : false,
      },
    })
  }, [connected, isAudioEnabled, isVideoEnabled, sendJson])

  useEffect(() => {
    if (!connected || typeof document === 'undefined') return

    const onVisibilityChange = () => {
      sendJson({
        type: 'client_status',
        data: {
          audio_muted: !isAudioEnabled,
          video_enabled: isVideoEnabled,
          tab_hidden: document.hidden,
        },
      })
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [connected, isAudioEnabled, isVideoEnabled, sendJson])

  // Attach stream to video element
  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream
    }
  }, [stream])

  // Send video frames at adaptive FPS (adjusted by backend target_fps)
  useEffect(() => {
    if (!connected || !stream || !canvasRef.current || !videoRef.current) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = 320
    canvas.height = 240

    const sendFrame = async () => {
      if (!isVideoEnabled) return
      if (!videoRef.current || videoRef.current.readyState < 2) return
      ctx.drawImage(videoRef.current, 0, 0, 320, 240)
      try {
        const data = await encodeVideoFrame(canvas)
        sendBinary(data)
      } catch {
        // ignore frame encoding errors
      }
    }

    const startInterval = () => {
      if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
      const intervalMs = Math.round(1000 / targetFpsRef.current)
      frameIntervalRef.current = setInterval(sendFrame, intervalMs)
    }

    startInterval()

    // Poll for FPS changes (set by onMessage when target_fps updates)
    const fpsCheckInterval = setInterval(() => {
      if (!frameIntervalRef.current) {
        // Interval was cleared by onMessage — restart with new FPS
        startInterval()
      }
    }, 500)

    return () => {
      if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
      clearInterval(fpsCheckInterval)
    }
  }, [connected, isVideoEnabled, stream, sendBinary])

  // Stream microphone audio as 16kHz mono PCM in 30ms chunks.
  useEffect(() => {
    if (!connected || !stream || stream.getAudioTracks().length === 0) return

    const AudioContextClass =
      window.AudioContext || window.webkitAudioContext

    if (!AudioContextClass) return

    const audioContext = new AudioContextClass({ sampleRate: 16000 })
    const source = audioContext.createMediaStreamSource(stream)
    const processor = audioContext.createScriptProcessor(4096, 1, 1)

    audioContextRef.current = audioContext
    audioSourceRef.current = source
    audioProcessorRef.current = processor
    audioSampleBufferRef.current = []

    const flushChunk = () => {
      while (audioSampleBufferRef.current.length >= 480) {
        const samples = audioSampleBufferRef.current.slice(0, 480)
        audioSampleBufferRef.current = audioSampleBufferRef.current.slice(480)
        const pcm = floatToPcm16(samples)
        sendBinary(encodeAudioChunk(pcm))
      }
    }

    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0)
      const resampled = resampleAudio(
        input,
        audioContext.sampleRate,
        16000
      )

      for (let i = 0; i < resampled.length; i++) {
        audioSampleBufferRef.current.push(resampled[i])
      }

      flushChunk()
    }

    source.connect(processor)
    processor.connect(audioContext.destination)
    void audioContext.resume().catch(() => {
      // ignore resume failures; browser may already be running
    })

    return () => {
      processor.onaudioprocess = null
      audioSampleBufferRef.current = []
      try {
        source.disconnect()
      } catch {
        // ignore disconnect errors
      }
      try {
        processor.disconnect()
      } catch {
        // ignore disconnect errors
      }
      void audioContext.close().catch(() => {
        // ignore close errors
      })
      audioContextRef.current = null
      audioSourceRef.current = null
      audioProcessorRef.current = null
    }
  }, [connected, stream, sendBinary])

  const isTutor = role === 'tutor' || currentMetrics !== null
  const hasAudioTrack = Boolean(stream?.getAudioTracks().length)
  const hasVideoTrack = Boolean(stream?.getVideoTracks().length)
  const engagementTrendLabel = currentMetrics
    ? currentMetrics.session.engagement_trend === 'rising'
      ? 'Rising'
      : currentMetrics.session.engagement_trend === 'declining'
      ? 'Declining'
      : 'Stable'
    : 'Stable'
  const minimalAttentionSummary = currentMetrics
    ? {
        label: 'Student attention',
        value: formatAttentionStateLabel(currentMetrics.student.attention_state),
        className: attentionPillClasses(currentMetrics.student.attention_state),
      }
    : null
  const minimalTalkSummary = currentMetrics
    ? talkBalanceSummary(currentMetrics)
    : null
  const minimalFlowSummary = currentMetrics
    ? flowSummary(currentMetrics)
    : null
  const remoteLabel = role === 'tutor' ? 'Student' : role === 'student' ? 'Tutor' : 'Participant'
  const localLabel = role === 'tutor' ? 'You (Tutor)' : role === 'student' ? 'You (Student)' : 'You'
  const roleBadgeLabel = isTutor
    ? 'Tutor workspace'
    : role === 'student'
    ? 'Student call view'
    : sessionInfoLoaded
    ? 'Preparing join view'
    : 'Preparing session'
  const roleSummaryText = isTutor
    ? 'You will see the live call plus private coaching cues that stay hidden from the student.'
    : role === 'student'
    ? 'This screen stays focused on the call. Tutor coaching, nudges, and analytics remain private to the tutor.'
    : 'We are confirming your role and preparing the correct session view.'
  const consentButtonLabel = sessionEnded
    ? isTutor
      ? 'View analytics'
      : 'Return home'
    : isTutor
    ? 'Join as Tutor'
    : role === 'student'
    ? 'Join as Student'
    : 'Join session'
  const controlTitle = isTutor ? 'Tutor controls' : 'Student controls'
  const controlDescription = isTutor
    ? 'Mute/camera toggles affect only this browser tab. Students never see your live coaching overlay or nudges.'
    : 'Mute/camera toggles affect only this browser tab. This student view stays call-first and does not show tutor coaching.'
  const secondaryHelperText = isTutor
    ? 'Use Coach debug only when you want richer diagnostics during the session.'
    : 'If you leave, the tutor will see that you disconnected and you can rejoin with the same link.'
  const callPlaceholderText =
    callStatus === 'connected'
      ? `Connected. Waiting for ${remoteLabel.toLowerCase()} video.`
      : callStatus === 'connecting'
      ? `Setting up ${isTutor ? 'your tutoring call' : 'the call'}...`
      : callStatus === 'reconnecting'
      ? `Trying to reconnect to the ${remoteLabel.toLowerCase()}...`
      : `Waiting for the ${remoteLabel.toLowerCase()} to join.`
  const sessionEndedMessage = isTutor
    ? 'The session has ended. Analytics are ready and you can review them now.'
    : 'The session has ended. You can safely leave this page.'
  const canShowDebugToggle = isTutor || showCoachDebug

  const handleEndSession = useCallback(async () => {
    if (!sessionId || !token || endingSession || sessionEnded) return
    if (!window.confirm('End this session for everyone?')) return

    setEndingSession(true)
    setEndSessionError(null)
    appendDebugEvent('manual end session requested')

    try {
      const response = await fetch(
        `${API_URL}/api/sessions/${sessionId}/end?token=${encodeURIComponent(token)}`,
        { method: 'POST' }
      )
      if (!response.ok) {
        throw new Error('Failed to end session')
      }
      setSessionEnded(true)
      setPeerDisconnected(false)
      appendDebugEvent('session end request accepted')
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to end session'
      setEndSessionError(message)
      appendDebugEvent(`session end failed: ${message}`)
    } finally {
      setEndingSession(false)
    }
  }, [appendDebugEvent, endingSession, sessionEnded, sessionId, token])

  const handleLeaveSession = useCallback(() => {
    if (sessionEnded) {
      appendDebugEvent('leaving ended session view')
      closeConnection('leaving ended session view')
      stopStream()
      if (isTutor) {
        router.push(`/analytics/${sessionId}`)
      } else {
        router.push('/')
      }
      return
    }

    if (!window.confirm('Leave this session? You can rejoin later with the same link.')) {
      return
    }

    appendDebugEvent('left session locally')
    closeConnection('left session locally')
    stopStream()
    router.push('/')
  }, [appendDebugEvent, closeConnection, isTutor, router, sessionEnded, sessionId, stopStream])

  if (showConsent) {
    return (
      <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_28%),radial-gradient(circle_at_bottom_right,_rgba(139,92,246,0.18),_transparent_32%),#020617] px-6 py-10 text-white">
        <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-5xl items-center justify-center">
          <div className="grid w-full gap-6 rounded-[32px] border border-white/10 bg-slate-950/75 p-6 shadow-[0_28px_120px_rgba(2,6,23,0.6)] backdrop-blur md:grid-cols-[1.1fr_0.9fr] md:p-8">
            <div className="space-y-6">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span
                    data-testid="session-perspective-badge"
                    className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] ${
                      isTutor
                        ? 'border-sky-400/40 bg-sky-500/10 text-sky-100'
                        : role === 'student'
                        ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
                        : 'border-white/15 bg-white/5 text-slate-200'
                    }`}
                  >
                    {roleBadgeLabel}
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
                    Session {sessionId}
                  </span>
                </div>
                <div>
                  <h1 className="text-3xl font-semibold tracking-tight text-white md:text-4xl">
                    {sessionEnded
                      ? isTutor
                        ? 'This tutoring session has already ended.'
                        : 'This session has ended.'
                      : isTutor
                      ? 'Enter the tutor workspace'
                      : role === 'student'
                      ? 'Join the student call view'
                      : 'Join the live session'}
                  </h1>
                  <p
                    data-testid="session-perspective-copy"
                    className="mt-4 max-w-2xl text-base leading-7 text-slate-300"
                  >
                    {sessionEnded ? sessionEndedMessage : roleSummaryText}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                    What is measured
                  </p>
                  <ul className="mt-3 space-y-2 text-sm text-slate-200">
                    <li>• camera-facing / gaze direction</li>
                    <li>• speaking time and turn-taking</li>
                    <li>• audio-primary energy / engagement signals</li>
                  </ul>
                </div>
                <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                    Privacy posture
                  </p>
                  <p className="mt-3 text-sm leading-6 text-slate-200">
                    Raw video and audio are not stored. Only derived numeric metrics are saved for post-session analytics.
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 md:p-6">
              <div className="space-y-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Before you join
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-white">
                    {isTutor
                      ? 'You will see a clean live call plus private tutor coaching.'
                      : role === 'student'
                      ? 'You will see only the live call and your local controls.'
                      : 'Allow camera and microphone to enter the session.'}
                  </h2>
                </div>

                <div className="space-y-3 rounded-3xl border border-white/10 bg-slate-950/45 p-4 text-sm text-slate-300">
                  <p>• Keep this tab open for the cleanest reconnect behavior.</p>
                  <p>• You can mute or turn your camera off after joining.</p>
                  <p>
                    • {sessionInfoLoaded
                      ? isTutor
                        ? 'Students never see your live coaching pills, nudges, or analytics.'
                        : 'If you leave, the tutor will see that you disconnected and you can return with the same invite link.'
                      : 'We are still confirming the exact role view, but the same privacy rules apply.'}
                  </p>
                </div>

                <button
                  data-testid="consent-start-button"
                  onClick={() => {
                    if (sessionEnded) {
                      handleLeaveSession()
                      return
                    }
                    setShowConsent(false)
                    requestAccess()
                  }}
                  className="w-full rounded-2xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500"
                >
                  {consentButtonLabel}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <div className="border-b border-white/10 bg-gray-900/90 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-3">
            <div
              className={`mt-1 h-3 w-3 rounded-full ${
                connected ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  data-testid="session-role-badge"
                  className={`rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] ${
                    isTutor
                      ? 'border-sky-400/40 bg-sky-500/10 text-sky-100'
                      : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
                  }`}
                >
                  {roleBadgeLabel}
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-slate-300">
                  Session {sessionId}
                </span>
              </div>
              <p className="mt-2 text-sm text-white">
                {connected ? 'Connected to session server' : 'Trying to reconnect to the session server'}
                {role && ` · ${role}`}
              </p>
              <p className="mt-1 text-xs text-gray-400">{roleSummaryText}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 self-end md:self-auto">
            {showCoachDebug && currentMetrics && (
              <div className="text-xs text-gray-400">
                Processing: {currentMetrics.server_processing_ms.toFixed(0)}ms
                {currentMetrics.degraded && (
                  <span className="ml-2 text-yellow-400">DEGRADED</span>
                )}
              </div>
            )}
            {canShowDebugToggle && (
              <button
                data-testid="coach-debug-toggle"
                type="button"
                onClick={() => setShowCoachDebug((prev) => !prev)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  showCoachDebug
                    ? 'border-blue-400/50 bg-blue-500/10 text-blue-100'
                    : 'border-gray-600 bg-gray-700/70 text-gray-200 hover:bg-gray-700'
                }`}
              >
                {showCoachDebug ? 'Hide debug' : isTutor ? 'Coach debug' : 'Debug panel'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-col items-center p-4 gap-4">
        {peerDisconnected && !sessionEnded && (
          <div data-testid="participant-disconnected-banner" className="w-full max-w-5xl rounded-2xl border border-yellow-700 bg-yellow-900/40 p-4 text-sm text-yellow-100">
            {remoteLabel} disconnected. They can rejoin within the grace window, and the call will attempt to recover automatically.
          </div>
        )}

        {sessionEnded && (
          <div data-testid="session-ended-banner" className="w-full max-w-5xl rounded-2xl border border-blue-700 bg-blue-900/40 p-4 text-sm text-blue-100">
            {sessionEndedMessage}
          </div>
        )}

        <div className="w-full max-w-5xl rounded-[24px] border border-gray-700 bg-gray-800 p-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="text-sm text-gray-300">
              <p className="font-medium text-white">{controlTitle}</p>
              <p>
                Mic: {hasAudioTrack ? (isAudioEnabled ? 'On' : 'Muted') : 'Unavailable'}
                {' • '}
                Camera: {hasVideoTrack ? (isVideoEnabled ? 'On' : 'Off') : 'Unavailable'}
              </p>
              <p className="mt-1 text-xs text-gray-400">{controlDescription}</p>
              <p className="mt-1 text-xs text-gray-500">{secondaryHelperText}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  toggleAudio()
                  appendDebugEvent(isAudioEnabled ? 'microphone muted locally' : 'microphone unmuted locally')
                }}
                disabled={!hasAudioTrack}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  isAudioEnabled
                    ? 'bg-gray-700 text-white hover:bg-gray-600'
                    : 'bg-red-600 text-white hover:bg-red-500'
                }`}
              >
                {isAudioEnabled ? 'Mute microphone' : 'Unmute microphone'}
              </button>
              <button
                type="button"
                onClick={() => {
                  toggleVideo()
                  appendDebugEvent(isVideoEnabled ? 'camera turned off locally' : 'camera turned on locally')
                }}
                disabled={!hasVideoTrack}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  isVideoEnabled
                    ? 'bg-gray-700 text-white hover:bg-gray-600'
                    : 'bg-red-600 text-white hover:bg-red-500'
                }`}
              >
                {isVideoEnabled ? 'Turn camera off' : 'Turn camera on'}
              </button>
              {!isTutor && (
                <button
                  data-testid="leave-session-button"
                  type="button"
                  onClick={handleLeaveSession}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/10"
                >
                  {sessionEnded ? 'Return home' : 'Leave session'}
                </button>
              )}
              {isTutor && sessionEnded && (
                <button
                  data-testid="view-analytics-button"
                  type="button"
                  onClick={handleLeaveSession}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/10"
                >
                  View analytics
                </button>
              )}
              {isTutor && (
                <button
                  data-testid="end-session-button"
                  type="button"
                  onClick={handleEndSession}
                  disabled={endingSession || sessionEnded}
                  className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {endingSession ? 'Ending…' : sessionEnded ? 'Session ended' : 'End for everyone'}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Call surface */}
        <div className="relative w-full max-w-5xl">
          <div data-testid="call-surface" className="relative aspect-video overflow-hidden rounded-[28px] border border-white/10 bg-black shadow-[0_24px_90px_rgba(0,0,0,0.45)]">
            {ENABLE_WEBRTC_CALL_UI ? (
              <>
                <video
                  data-testid="remote-video"
                  ref={remoteVideoRef}
                  autoPlay
                  playsInline
                  className={`absolute inset-0 h-full w-full object-cover transition-opacity ${
                    hasRemoteVideo ? 'opacity-100' : 'opacity-0'
                  }`}
                />

                {!hasRemoteVideo && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.14),_transparent_38%),radial-gradient(circle_at_bottom,_rgba(16,185,129,0.14),_transparent_34%),#050816] px-6 text-center text-gray-200">
                    <div data-testid="call-status-placeholder" className={`rounded-full border px-4 py-1.5 text-xs font-medium ${callStatusClasses(callStatus)}`}>
                      {callStatusLabel(callStatus)}
                    </div>
                    <div>
                      <p className="text-lg font-medium text-white">{remoteLabel}</p>
                      <p className="mt-1 text-sm text-gray-400">
                        {callPlaceholderText}
                      </p>
                    </div>
                    {ENABLE_WEBRTC_CALL_UI && !hasRemoteAudio && callStatus === 'connected' && (
                      <p className="text-xs text-gray-500">Remote audio not detected yet.</p>
                    )}
                  </div>
                )}

                <div className="absolute left-4 top-4 flex items-center gap-2">
                  <div data-testid="call-status-badge" className={`rounded-full border px-3 py-1 text-xs font-medium backdrop-blur-md ${callStatusClasses(callStatus)}`}>
                    {callStatusLabel(callStatus)}
                  </div>
                  {peerDisconnected && !sessionEnded && (
                    <div className="rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-100 backdrop-blur-md">
                      Reconnect grace active
                    </div>
                  )}
                </div>

                <div className="absolute bottom-4 left-4 rounded-full border border-white/15 bg-black/45 px-3 py-1 text-xs font-medium text-white backdrop-blur-md">
                  {remoteLabel}
                </div>

                {callStatus === 'connected' && !hasRemoteAudio && (
                  <div className="absolute right-4 top-4 rounded-full border border-white/15 bg-black/45 px-3 py-1 text-xs font-medium text-white backdrop-blur-md">
                    Remote audio unavailable
                  </div>
                )}

                <div className="absolute bottom-4 right-4 w-40 overflow-hidden rounded-2xl border border-white/15 bg-black/80 shadow-lg sm:w-52">
                  <video
                    data-testid="local-video"
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    className="aspect-video h-full w-full object-cover"
                  />
                  {!isVideoEnabled && hasVideoTrack && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-xs text-gray-200">
                      Camera off
                    </div>
                  )}
                  <div className="absolute bottom-2 left-2 rounded-full border border-white/10 bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-md">
                    {localLabel}
                  </div>
                </div>
              </>
            ) : (
              <>
                <video
                  ref={videoRef}
                  autoPlay
                  muted
                  playsInline
                  className="h-full w-full object-cover"
                />
                {!isVideoEnabled && hasVideoTrack && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/75 text-sm text-gray-200">
                    Camera is off
                  </div>
                )}
              </>
            )}

            <canvas ref={canvasRef} className="hidden" />

            {/* Minimal tutor overlay */}
            {isTutor && currentMetrics && minimalAttentionSummary && minimalTalkSummary && minimalFlowSummary && (
              <div data-testid="coach-overlay" className="pointer-events-none absolute left-3 right-3 top-16 flex flex-wrap items-start gap-2">
                {[minimalAttentionSummary, minimalTalkSummary, minimalFlowSummary].map((pill) => (
                  <div
                    key={pill.label}
                    className={`rounded-full border px-3 py-1.5 text-[11px] font-medium tracking-[0.02em] backdrop-blur-md ${pill.className}`}
                  >
                    <span className="mr-2 text-[10px] uppercase tracking-[0.16em] text-white/55">
                      {pill.label}
                    </span>
                    <span>{pill.value}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Detailed metrics overlay (debug only) */}
            {showCoachDebug && isTutor && currentMetrics && (
              <div className="absolute left-3 right-3 top-28 rounded-2xl border border-white/10 bg-black/55 p-3 text-xs text-white backdrop-blur-md">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-1">
                    <div
                      className={`h-2 w-2 rounded-full ${
                        currentMetrics.gaze_unavailable
                          ? 'bg-gray-400'
                          : currentMetrics.student.eye_contact_score > 0.7
                          ? 'bg-green-400'
                          : currentMetrics.student.eye_contact_score > 0.4
                          ? 'bg-yellow-400'
                          : 'bg-red-400'
                      }`}
                    />
                    <span>
                      Student camera-facing:{' '}
                      {currentMetrics.gaze_unavailable
                        ? 'unavailable'
                        : `${(currentMetrics.student.eye_contact_score * 100).toFixed(0)}%`}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 ${currentMetrics.tutor.is_speaking ? 'bg-blue-500/30 text-blue-100' : 'bg-gray-700 text-gray-200'}`}>
                      Tutor {currentMetrics.tutor.is_speaking ? 'speaking' : 'silent'}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 ${currentMetrics.student.is_speaking ? 'bg-green-500/30 text-green-100' : 'bg-gray-700 text-gray-200'}`}>
                      Student {currentMetrics.student.is_speaking ? 'speaking' : 'silent'}
                    </span>
                  </div>

                  <div className="min-w-[220px] flex-1">
                    <div className="mb-0.5 flex justify-between text-[10px]">
                      <span>
                        Talk share · Tutor {(currentMetrics.tutor.talk_time_percent * 100).toFixed(0)}%
                      </span>
                      <span>
                        Student {(currentMetrics.student.talk_time_percent * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex h-1.5 overflow-hidden rounded-full bg-gray-600">
                      <div
                        className="h-full bg-blue-400"
                        style={{ width: `${currentMetrics.tutor.talk_time_percent * 100}%` }}
                      />
                      <div
                        className="h-full bg-green-400"
                        style={{ width: `${currentMetrics.student.talk_time_percent * 100}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    Trend: {engagementTrendLabel} · Score {currentMetrics.session.engagement_score.toFixed(0)}
                  </div>

                  <div>
                    Student silence: {currentMetrics.session.time_since_student_spoke.toFixed(0)}s
                  </div>

                  <div>
                    Tutor monologue: {currentMetrics.session.tutor_monologue_duration_current.toFixed(0)}s
                  </div>

                  <div>
                    Overlaps: {currentMetrics.session.interruption_count}
                    {currentMetrics.session.active_overlap_state !== 'none' && (
                      <span className="ml-1 text-orange-300">
                        · live {currentMetrics.session.active_overlap_state} {currentMetrics.session.active_overlap_duration_current.toFixed(1)}s
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Nudge toasts (tutor only) */}
        {isTutor && nudges.length > 0 && (
          <div className="fixed bottom-4 right-4 z-50 max-w-sm space-y-2">
            {nudges.map((nudge) => (
              <div
                key={nudge.id}
                className={`rounded-2xl border p-4 shadow-xl transition-all ${
                  nudge.priority === 'high'
                    ? 'border-red-700 bg-red-950/92'
                    : nudge.priority === 'medium'
                    ? 'border-yellow-700 bg-yellow-950/92'
                    : 'border-gray-700 bg-gray-900/92'
                }`}
              >
                <p className="text-sm font-medium text-white">{nudge.message}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => dismissNudge(nudge.id)}
                    className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/10"
                  >
                    Close
                  </button>
                  <button
                    type="button"
                    onClick={disableAllNudges}
                    className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/10"
                  >
                    Disable all nudges for session
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {isTutor && !nudgesEnabled && (
          <div className="fixed bottom-4 right-4 z-40 rounded-full border border-white/10 bg-gray-900/90 px-3 py-2 text-xs text-gray-200 shadow-lg">
            Live nudges disabled for this session.
          </div>
        )}

        {showCoachDebug && (
          <div data-testid="coach-debug-panel" className="w-full max-w-5xl rounded-lg border border-gray-700 bg-gray-800/80">
            <div className="flex items-center justify-between px-4 py-3 text-sm font-medium text-white">
              <span>Debug panel</span>
              <div className="flex items-center gap-2">
                {!nudgesEnabled && (
                  <button
                    type="button"
                    onClick={enableAllNudges}
                    className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white transition-colors hover:bg-white/10"
                  >
                    Re-enable nudges
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setShowCoachDebug(false)}
                  className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white transition-colors hover:bg-white/10"
                >
                  Hide
                </button>
              </div>
            </div>
            <div className="grid gap-4 border-t border-gray-700 px-4 py-4 text-sm md:grid-cols-2">
              <div className="space-y-2">
                <h3 className="font-semibold text-white">Connection + local state</h3>
                <div className="space-y-1 text-gray-300">
                  <p>Session ID: <code>{sessionId}</code></p>
                  <p>Role: {role ?? 'unknown'}</p>
                  <p>Connected: {connected ? 'yes' : 'no'}</p>
                  <p>Token present: {token ? 'yes' : 'no'}</p>
                  <p>Mic enabled: {isAudioEnabled ? 'yes' : 'no'}</p>
                  <p>Camera enabled: {isVideoEnabled ? 'yes' : 'no'}</p>
                  <p>Session ended: {sessionEnded ? 'yes' : 'no'}</p>
                  <p>Live nudges enabled: {nudgesEnabled ? 'yes' : 'no'}</p>
                  <p data-testid="debug-media-provider">Media provider: {mediaProvider}</p>
                  <p data-testid="debug-webrtc-enabled">WebRTC enabled: {ENABLE_WEBRTC_CALL_UI ? 'yes' : 'no'}</p>
                  <p data-testid="debug-call-status">Call status: {callStatusLabel(callStatus)}</p>
                  <p data-testid="debug-peer-connection-state">Peer connection state: {connectionState}</p>
                  <p data-testid="debug-ice-connection-state">ICE connection state: {iceConnectionState}</p>
                  <p data-testid="debug-ice-gathering-state">ICE gathering state: {iceGatheringState}</p>
                  <p data-testid="debug-signaling-state">Signaling state: {signalingState}</p>
                  <p data-testid="debug-remote-tracks">Remote tracks: {remoteTrackCount}</p>
                  <p data-testid="debug-remote-video-present">Remote video present: {hasRemoteVideo ? 'yes' : 'no'}</p>
                  <p data-testid="debug-remote-audio-present">Remote audio present: {hasRemoteAudio ? 'yes' : 'no'}</p>
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="font-semibold text-white">Current metrics</h3>
                {currentMetrics ? (
                  <div data-testid="debug-current-metrics" className="space-y-1 text-gray-300">
                    <p>Student attention state: {formatAttentionStateLabel(currentMetrics.student.attention_state)}</p>
                    <p>Student attention confidence: {(currentMetrics.student.attention_state_confidence * 100).toFixed(1)}%</p>
                    <p>Student face presence: {(currentMetrics.student.face_presence_score * 100).toFixed(1)}%</p>
                    <p>Student visual attention score: {(currentMetrics.student.visual_attention_score * 100).toFixed(1)}%</p>
                    <p>Student camera-facing score: {(currentMetrics.student.eye_contact_score * 100).toFixed(1)}%</p>
                    <p>Tutor attention state: {formatAttentionStateLabel(currentMetrics.tutor.attention_state)}</p>
                    <p>Tutor talk share: {(currentMetrics.tutor.talk_time_percent * 100).toFixed(1)}%</p>
                    <p>Student talk share: {(currentMetrics.student.talk_time_percent * 100).toFixed(1)}%</p>
                    <p>Tutor speaking now: {currentMetrics.tutor.is_speaking ? 'yes' : 'no'}</p>
                    <p>Student speaking now: {currentMetrics.student.is_speaking ? 'yes' : 'no'}</p>
                    <p>Student silence timer: {currentMetrics.session.time_since_student_spoke.toFixed(1)}s</p>
                    <p>Mutual silence timer: {currentMetrics.session.mutual_silence_duration_current.toFixed(1)}s</p>
                    <p>Tutor monologue timer: {currentMetrics.session.tutor_monologue_duration_current.toFixed(1)}s</p>
                    <p>Tutor turns: {currentMetrics.session.tutor_turn_count}</p>
                    <p>Student turns: {currentMetrics.session.student_turn_count}</p>
                    <p>Last student response latency: {currentMetrics.session.student_response_latency_last_seconds.toFixed(1)}s</p>
                    <p>Last tutor response latency: {currentMetrics.session.tutor_response_latency_last_seconds.toFixed(1)}s</p>
                    <p>Total overlaps: {currentMetrics.session.interruption_count}</p>
                    <p>Active overlap: {currentMetrics.session.active_overlap_state} ({currentMetrics.session.active_overlap_duration_current.toFixed(1)}s)</p>
                    <p>Hard interruptions: {currentMetrics.session.hard_interruption_count}</p>
                    <p>Recent hard interruptions: {currentMetrics.session.recent_hard_interruptions}</p>
                    <p>Backchannels: {currentMetrics.session.backchannel_overlap_count}</p>
                    <p>Recent backchannels: {currentMetrics.session.recent_backchannel_overlaps}</p>
                    <p>Echo suspected: {currentMetrics.session.echo_suspected ? 'yes' : 'no'}</p>
                    <p>Tutor cutoffs: {currentMetrics.session.tutor_cutoffs}</p>
                    <p>Engagement trend: {engagementTrendLabel}</p>
                    <p>Engagement score: {currentMetrics.session.engagement_score.toFixed(1)}</p>
                    <p>Target FPS: {currentMetrics.target_fps}</p>
                    <p>Processing ms: {currentMetrics.server_processing_ms.toFixed(1)}</p>
                  </div>
                ) : (
                  <p data-testid="debug-no-live-metrics" className="text-gray-400">No live metrics yet.</p>
                )}
              </div>

              <div className="space-y-2 md:col-span-2">
                <h3 className="font-semibold text-white">Recent events</h3>
                <div className="max-h-48 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-300 space-y-1">
                  {debugEvents.length > 0 ? (
                    debugEvents.slice().reverse().map((event, index) => (
                      <p key={`${event.at}-${index}`}>
                        <span className="text-gray-500">[{event.at}]</span> {event.message}
                      </p>
                    ))
                  ) : (
                    <p className="text-gray-500">No events yet.</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="font-semibold text-white">Nudges seen</h3>
                <div className="max-h-40 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-300 space-y-1">
                  {nudgeHistory.length > 0 ? (
                    nudgeHistory.slice().reverse().map((nudge) => (
                      <p key={nudge.id}>
                        <span className="text-gray-500">{nudge.priority}</span> · {nudge.nudge_type} · {nudge.message}
                      </p>
                    ))
                  ) : (
                    <p className="text-gray-500">No nudges yet.</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="font-semibold text-white">Raw snapshot</h3>
                <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-300 whitespace-pre-wrap break-words">
                  {currentMetrics ? JSON.stringify(currentMetrics, null, 2) : 'No metrics yet.'}
                </pre>
              </div>

              <div className="space-y-2 md:col-span-2">
                <h3 className="font-semibold text-white">History</h3>
                <p className="text-xs text-gray-400">
                  Metrics snapshots kept in memory: {metricsHistory.length}. Live nudge history: {nudgeHistory.length}.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Errors */}
        {(mediaError || wsError || peerError || endSessionError) && (
          <div className="bg-red-900/50 border border-red-700 rounded-lg p-3 text-sm w-full max-w-5xl">
            {mediaError && <p>Media: {mediaError}</p>}
            {wsError && <p>Connection: {wsError}</p>}
            {peerError && <p>WebRTC: {peerError}</p>}
            {endSessionError && <p>Session: {endSessionError}</p>}
          </div>
        )}
      </div>
    </div>
  )
}
