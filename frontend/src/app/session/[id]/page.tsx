'use client'

import Image from 'next/image'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { signIn, useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useMediaStream } from '@/hooks/useMediaStream'
import { useMetrics } from '@/hooks/useMetrics'
import { useNudges } from '@/hooks/useNudges'
import { useCallTransport } from '@/hooks/useCallTransport'
import { useTranscript } from '@/hooks/useTranscript'
import { useUncertainty } from '@/hooks/useUncertainty'
import { useAISuggestion } from '@/hooks/useAISuggestion'
import { MetricCard } from '@/components/charts'
import { TranscriptPanel } from '@/components/transcript'
import { AISuggestionCard, SuggestButton } from '@/components/coaching'
import {
  MicIcon,
  MicOffIcon,
  CameraIcon,
  CameraOffIcon,
  PhoneOffIcon,
} from '@/components/icons'
import {
  formatMinutes,
  formatPercent,
  formatScore,
  getSessionHealth,
  getTutorTalkTarget,
  isTalkBalanced,
  type AnalyticsTone,
} from '@/lib/analytics'
import { clearActiveSession } from '@/lib/active-session'
import { API_URL, ENABLE_WEBRTC_CALL_UI } from '@/lib/constants'
import { resolveMediaProvider } from '@/lib/call/provider'
import { encodeVideoFrame, encodeAudioChunk } from '@/lib/frameEncoder'
import { apiFetch } from '@/lib/api-client'
import { coachingStatusSummary } from '@/lib/coaching-status'
import type {
  MetricsSnapshot,
  Nudge,
  RemoteParticipant,
  SessionInfo,
  SessionSummary,
  WSMessage,
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

function analyticsToneClasses(tone: AnalyticsTone) {
  switch (tone) {
    case 'emerald':
      return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'
    case 'amber':
      return 'border-amber-400/30 bg-amber-400/10 text-amber-100'
    case 'rose':
      return 'border-rose-400/30 bg-rose-400/10 text-rose-100'
    case 'violet':
      return 'border-violet-400/30 bg-violet-400/10 text-violet-100'
    default:
      return 'border-white/10 bg-white/5 text-slate-200'
  }
}

/**
 * Derive a human-readable display name from a LiveKit participant identity.
 * Expected formats: `{sessionId}:tutor` or `{sessionId}:student:{N}`.
 */
function deriveDisplayName(identity: string): string {
  const parts = identity.split(':')
  if (parts.length >= 3) {
    const role = parts[parts.length - 2]
    const idx = parts[parts.length - 1]
    if (role === 'student' && /^\d+$/.test(idx)) {
      return `Student ${Number(idx) + 1}`
    }
  }
  const last = parts[parts.length - 1]
  if (last === 'tutor') return 'Tutor'
  if (last === 'student') return 'Student 1'
  return identity
}

function compareParticipantIdentity(a: RemoteParticipant, b: RemoteParticipant): number {
  const tutorSuffix = ':tutor'
  if (a.identity.endsWith(tutorSuffix) && !b.identity.endsWith(tutorSuffix)) return -1
  if (!a.identity.endsWith(tutorSuffix) && b.identity.endsWith(tutorSuffix)) return 1

  const studentPattern = /:student:(\d+)$/
  const aMatch = a.identity.match(studentPattern)
  const bMatch = b.identity.match(studentPattern)
  if (aMatch && bMatch) {
    return Number(aMatch[1]) - Number(bMatch[1])
  }

  return a.identity.localeCompare(b.identity)
}

function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

async function copyToClipboard(text: string) {
  if (!navigator.clipboard?.writeText) {
    throw new Error('Clipboard API unavailable')
  }

  await navigator.clipboard.writeText(text)
}

function buildStudentInviteUrl(sessionId: string, studentToken: string) {
  return `${window.location.origin}/session/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(studentToken)}`
}

/** Renders a single participant video tile for the multi-participant grid. */
function ParticipantTile({ participant }: { participant: RemoteParticipant }) {
  const tileVideoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (tileVideoRef.current) {
      tileVideoRef.current.srcObject = participant.stream
      void tileVideoRef.current.play().catch(() => {
        // Ignore autoplay policy errors during stream setup
      })
    }
  }, [participant.stream])

  return (
    <div
      data-testid="participant-tile"
      className="relative overflow-hidden rounded-xl bg-black"
    >
      <video
        ref={tileVideoRef}
        autoPlay
        playsInline
        className="h-full w-full object-cover"
      />
      {!participant.hasVideo && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-xs text-gray-300">
          No video
        </div>
      )}
      <div className="absolute bottom-2 left-2 rounded-full border border-white/15 bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-md">
        {deriveDisplayName(participant.identity)}
      </div>
    </div>
  )
}

export default function SessionPage() {
  const routeParams = useParams<{ id: string }>()
  const router = useRouter()
  const sessionId = routeParams.id
  const searchParams = useSearchParams()
  const token = searchParams.get('token') || ''
  const { data: authSession, status: authStatus, update: updateSession } = useSession()
  const userAccessToken = authSession?.user?.accessToken

  const [role, setRole] = useState<SessionRole | null>(null)
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)
  const [sessionInfoLoaded, setSessionInfoLoaded] = useState(false)
  const [showConsent, setShowConsent] = useState(true)
  const [analysisConsent, setAnalysisConsent] = useState(false)
  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const previewVideoRef = useRef<HTMLVideoElement>(null)
  const previewStreamRef = useRef<MediaStream | null>(null)
  const [sessionEnded, setSessionEnded] = useState(false)
  const [peerDisconnected, setPeerDisconnected] = useState(false)
  const [endingSession, setEndingSession] = useState(false)
  const [endSessionError, setEndSessionError] = useState<string | null>(null)
  const [showEndSummary, setShowEndSummary] = useState(false)
  const [endSummary, setEndSummary] = useState<SessionSummary | null>(null)
  const [endSummaryRecommendations, setEndSummaryRecommendations] = useState<string[]>([])
  const [endSummaryLoading, setEndSummaryLoading] = useState(false)
  const [endSummaryFailed, setEndSummaryFailed] = useState(false)
  const [debugEvents, setDebugEvents] = useState<Array<{ at: string; message: string }>>([])
  const [showConfirmLeave, setShowConfirmLeave] = useState(false)
  const [showConfirmEnd, setShowConfirmEnd] = useState(false)
  const [showCoachDebug, setShowCoachDebug] = useState(
    searchParams.get('debug') === '1'
  )
  const [sessionStartTime, setSessionStartTime] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [showInviteMenu, setShowInviteMenu] = useState(false)
  const inviteMenuRef = useRef<HTMLDivElement>(null)

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
      | { type: 'session_end' }
    >
  >([])
  const peerHandlersRef = useRef({
    handleParticipantReady: async () => {},
    handleParticipantDisconnected: () => {},
    handleParticipantReconnected: async () => {},
    closeConnection: (_reason: string) => {},
  })
  const activeSessionClearedRef = useRef(false)
  const endSummaryRequestedRef = useRef(false)
  const guestAutoCreatedRef = useRef(false)

  // Tracks whether user_auth has been sent for the current WebSocket connection.
  // Used to guarantee user_auth is the first text frame before client_status.
  const [userAuthSent, setUserAuthSent] = useState(false)

  // Tracks whether the auth state for this connection has definitively settled.
  // For authenticated users this is true immediately (they already have a token).
  // For unauthenticated students it becomes true only after the guest auto-create
  // attempt finishes (success or failure), preventing client_status from racing
  // ahead of user_auth during async guest sign-in.
  // For tutors (who never go through guest creation) it becomes true once the
  // role is known from the session info load.
  const [guestAuthSettled, setGuestAuthSettled] = useState(false)

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
    nudgeSoundEnabled,
    aiSuggestionFromNudge,
    handleNudge,
    dismissNudge,
    disableAllNudges,
    enableAllNudges,
    toggleNudgeSound,
    clearAiSuggestionFromNudge,
  } = useNudges()
  const isTutorRole = role === 'tutor' || currentMetrics !== null
  const transcriptionEnabled = sessionInfo?.enable_transcription === true

  const {
    messages: transcriptMessages,
    handleTranscriptMessage,
    handleTranscriptPacket,
    clearTranscript,
  } = useTranscript()

  const { uncertainty, handleUncertaintyMetrics } = useUncertainty()

  const {
    suggestion: aiSuggestion,
    loading: aiSuggestionLoading,
    callsRemaining: aiCallsRemaining,
    requestSuggestion,
    submitFeedback: submitSuggestionFeedback,
    clearSuggestion,
  } = useAISuggestion({ sessionId, accessToken: userAccessToken })

  const [transcriptPanelOpen, setTranscriptPanelOpen] = useState(false)
  const activeAISuggestion = aiSuggestion ?? aiSuggestionFromNudge

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

  // Settle guestAuthSettled for cases where no guest creation is needed:
  //   • User is already authenticated → token is available right away.
  //   • Role is 'tutor' (once known) → tutors never go through guest creation.
  // For unauthenticated students the flag is set inside the guest auto-create
  // effect's finally block (below) so that client_status is held until the
  // async sign-in completes.
  useEffect(() => {
    if (authStatus === 'authenticated') {
      setGuestAuthSettled(true)
      return
    }
    if (sessionInfoLoaded && role === 'tutor') {
      setGuestAuthSettled(true)
    }
    // For unauthenticated students: settled by the guest auto-create finally block.
    // For authStatus === 'loading': wait until auth resolves.
  }, [authStatus, sessionInfoLoaded, role])

  // When a student opens a session link without being signed in, silently
  // create a guest account and sign them in.  This allows the backend to
  // associate their WebSocket connection with a user ID via the user_auth
  // message, enabling student-side session history.  The effect is intentionally
  // fire-and-forget — if it fails, the session join still proceeds normally but
  // without authenticated session history tracking.
  //
  // We wait for sessionInfoLoaded so we know the role from the session token
  // before creating a guest.  This prevents an unauthenticated tutor-link opener
  // from being silently created as a student-role guest account.
  useEffect(() => {
    if (!sessionInfoLoaded || role !== 'student') return
    if (authStatus !== 'unauthenticated' || guestAutoCreatedRef.current) return

    guestAutoCreatedRef.current = true

    fetch(`${API_URL}/api/auth/guest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(async (res) => {
        if (!res.ok) return
        const data = (await res.json()) as { access_token?: string }
        if (!data.access_token) return

        const result = await signIn('credentials', {
          token: data.access_token,
          redirect: false,
        })
        if (result?.ok) {
          await updateSession()
        }
      })
      .catch(() => {
        // Silent failure — session analytics tracking will proceed without user ID
      })
      .finally(() => {
        // Mark auth as settled so client_status can proceed (with or without a
        // token).  If guest creation succeeded, user_auth will have been sent
        // before client_status because userAccessToken will now be non-null and
        // the user_auth effect fires before the guestAuthSettled gate lifts for
        // client_status (the effects run in dependency order on the same cycle).
        setGuestAuthSettled(true)
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, sessionInfoLoaded, role])

  useEffect(() => {
    if (!sessionId || !token) return

    apiFetch(
      `/api/sessions/${sessionId}/info?token=${encodeURIComponent(token)}`,
      { accessToken: userAccessToken }
    )
      .then((res) => res.json())
      .then((data: SessionInfo) => {
        setSessionInfo(data)
        if (data.role === 'tutor' || data.role === 'student') {
          setRole(data.role)
          appendDebugEvent(
            `session info loaded (${data.role}, provider=${data.media_provider}, analytics=${data.analytics_ingest_mode ?? 'browser_upload'})`
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
          handleUncertaintyMetrics(metrics)
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
        case 'transcript_partial':
        case 'transcript_final': {
          handleTranscriptMessage(message)
          const td = message.data as unknown as Record<string, unknown>
          const tp = typeof td?.text === 'string' ? td.text.slice(0, 40) : '?'
          appendDebugEvent(`[ws] ${message.type}: "${tp}"`)
          break
        }
        // webrtc_signal messages are no longer used (LiveKit handles media transport)
      }
    },
    [appendDebugEvent, handleMetrics, handleNudge, handleTranscriptMessage, handleUncertaintyMetrics, queuePeerEvent]
  )

  const { connected, error: wsError, sendBinary, sendJson } = useWebSocket({
    sessionId,
    token,
    debug: searchParams.get('debug') === '1',
    onMessage,
  })

  const handleDataPacket = useCallback(
    (topic: string, payload: Uint8Array) => {
      try {
        const text = new TextDecoder().decode(payload)
        const message = JSON.parse(text) as { type: string; data: unknown }

        if (message.type === 'metrics') {
          setRole('tutor')
          const metrics = message.data as MetricsSnapshot
          handleMetrics(metrics)
          handleUncertaintyMetrics(metrics)
          appendDebugEvent(
            `[data-pkt] metrics: attention=${metrics.student.attention_state}`
          )
          const newFps = metrics.target_fps
          if (newFps && newFps !== targetFpsRef.current && newFps >= 1 && newFps <= 10) {
            targetFpsRef.current = newFps
            if (frameIntervalRef.current) {
              clearInterval(frameIntervalRef.current)
              frameIntervalRef.current = null
            }
          }
        } else if (message.type === 'nudge') {
          setRole('tutor')
          handleNudge(message.data as Nudge)
          appendDebugEvent(`[data-pkt] nudge: ${(message.data as Nudge).nudge_type}`)
        } else if (
          message.type === 'transcript_partial' ||
          message.type === 'transcript_final'
        ) {
          handleTranscriptMessage(message as WSMessage)
          const d = message.data as unknown as Record<string, unknown>
          const preview = typeof d?.text === 'string' ? d.text.slice(0, 40) : '?'
          appendDebugEvent(`[data-pkt] ${message.type}: "${preview}"`)
        }
      } catch {
        // ignore malformed data packets
      }
    },
    [appendDebugEvent, handleMetrics, handleNudge, handleTranscriptMessage, handleUncertaintyMetrics]
  )

  const mediaProvider = resolveMediaProvider(sessionInfo)
  const analyticsIngestMode = sessionInfo?.analytics_ingest_mode ?? 'browser_upload'
  const browserAnalyticsUploadEnabled = analyticsIngestMode !== 'livekit_worker'

  const {
    remoteStream,
    remoteTrackCount,
    hasRemoteVideo,
    hasRemoteAudio,
    remoteParticipants,
    callStatus,
    connectionState,
    iceConnectionState,
    iceGatheringState,
    signalingState,
    error: peerError,
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
    accessToken: userAccessToken,
    debug: searchParams.get('debug') === '1',
    sendSignal: () => {},
    onDebugEvent: appendDebugEvent,
    onDataPacket: useCallback(
      (topic: string, payload: Uint8Array) => {
        handleDataPacket(topic, payload)
        handleTranscriptPacket(topic, payload)
      },
      [handleDataPacket, handleTranscriptPacket]
    ),
  })

  useEffect(() => {
    peerHandlersRef.current = {
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
  ])

  useEffect(() => {
    if (!sessionEnded || activeSessionClearedRef.current) return

    activeSessionClearedRef.current = true
    clearActiveSession()
    appendDebugEvent('cleared active session')
  }, [appendDebugEvent, sessionEnded])

  // Clear active session when tutor explicitly leaves (via leave/end buttons).
  // The leave handler already calls clearActiveSession via confirmLeaveSession,
  // and session-end clears it above. We also clear on beforeunload (tab close)
  // since the user won't return to this page.
  useEffect(() => {
    if (!isTutorRole) return
    const handleBeforeUnload = () => clearActiveSession()
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isTutorRole])

  // Auto-redirect students to dashboard when session ends
  useEffect(() => {
    if (!sessionEnded || isTutorRole) return
    const redirectTimer = setTimeout(() => {
      closeConnection('session ended — student redirect')
      stopStream()
      router.push('/')
    }, 3500)
    return () => clearTimeout(redirectTimer)
  }, [closeConnection, isTutorRole, router, sessionEnded, stopStream])

  useEffect(() => {
    if (!sessionEnded || !isTutorRole || !sessionId) return

    setShowEndSummary(true)

    if (endSummaryRequestedRef.current) {
      return
    }

    endSummaryRequestedRef.current = true
    setEndSummaryLoading(true)
    setEndSummaryFailed(false)
    setEndSummary(null)
    setEndSummaryRecommendations([])
    appendDebugEvent('fetching end-of-session summary')

    let cancelled = false

    Promise.allSettled([
      apiFetch(`/api/analytics/sessions/${sessionId}`, { accessToken: userAccessToken }).then(async (response) => {
        if (!response.ok) {
          throw new Error('Session summary not ready')
        }

        return (await response.json()) as SessionSummary | null
      }),
      apiFetch(`/api/analytics/sessions/${sessionId}/recommendations`, { accessToken: userAccessToken }).then(
        async (response) => {
          if (!response.ok) {
            return []
          }

          return (await response.json()) as unknown
        }
      ),
    ])
      .then(([summaryResult, recommendationsResult]) => {
        if (cancelled) return

        if (summaryResult.status === 'fulfilled' && summaryResult.value) {
          setEndSummary(summaryResult.value)
          setEndSummaryFailed(false)
          appendDebugEvent('session report ready')
        } else {
          setEndSummary(null)
          setEndSummaryFailed(true)
          appendDebugEvent(
            'session report unavailable; falling back to analytics link'
          )
        }

        if (recommendationsResult.status === 'fulfilled') {
          setEndSummaryRecommendations(
            Array.isArray(recommendationsResult.value)
              ? recommendationsResult.value.filter(
                  (value): value is string => typeof value === 'string'
                )
              : []
          )
        }
      })
      .catch(() => {
        if (cancelled) return

        setEndSummary(null)
        setEndSummaryFailed(true)
        setEndSummaryRecommendations([])
        appendDebugEvent('session report request failed')
      })
      .finally(() => {
        if (!cancelled) {
          setEndSummaryLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [appendDebugEvent, isTutorRole, sessionEnded, sessionId])

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

  // Send user_auth as the first text frame when the WebSocket connects so the
  // backend can associate this participant with their authenticated user account.
  // This must fire before client_status to ensure room.student_user_id is set
  // before session finalization writes the SessionSummary.
  //
  // The effect also resets userAuthSent when the connection drops so that
  // user_auth is re-sent on the next successful reconnect.
  useEffect(() => {
    if (!connected) {
      setUserAuthSent(false)
      return
    }
    if (!userAccessToken || userAuthSent) return
    setUserAuthSent(true)
    sendJson({
      type: 'user_auth',
      data: {
        access_token: userAccessToken,
      },
    })
  }, [connected, userAccessToken, userAuthSent, sendJson])

  // Send client_status after user_auth has been sent (when a token exists),
  // guaranteeing user_auth is always the first text frame for authenticated
  // connections.
  //
  // guestAuthSettled gates this for unauthenticated students: it becomes true
  // only after the async guest creation attempt finishes, ensuring user_auth
  // (dispatched by the effect above once userAccessToken is available) is sent
  // before client_status regardless of network timing.
  useEffect(() => {
    if (!connected) return
    // Wait until auth has settled — prevents client_status racing ahead of
    // user_auth during async guest sign-in for student visitors.
    if (!guestAuthSettled) return
    // If we have a token, wait until user_auth has been sent first.
    if (userAccessToken && !userAuthSent) return
    sendJson({
      type: 'client_status',
      data: {
        audio_muted: !isAudioEnabled,
        video_enabled: isVideoEnabled,
        tab_hidden: typeof document !== 'undefined' ? document.hidden : false,
      },
    })
  }, [connected, guestAuthSettled, userAccessToken, userAuthSent, isAudioEnabled, isVideoEnabled, sendJson])

  useEffect(() => {
    if (!connected || typeof document === 'undefined') return

    const onVisibilityChange = () => {
      // Apply the same auth-ordering gate as the main client_status effect:
      // do not send client_status before user_auth has been confirmed sent.
      // This prevents a tab-background/visibility event from racing ahead of
      // user_auth during async guest sign-in for student visitors.
      if (!guestAuthSettled) return
      if (userAccessToken && !userAuthSent) return

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
  }, [connected, guestAuthSettled, userAccessToken, userAuthSent, isAudioEnabled, isVideoEnabled, sendJson])

  // Attach stream to video element
  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream
    }
  }, [stream])

  useEffect(() => {
    previewStreamRef.current = previewStream
  }, [previewStream])

  // Attach preview stream to preview video element
  useEffect(() => {
    if (!previewVideoRef.current) return
    previewVideoRef.current.srcObject = previewStream
    if (previewStream) {
      void previewVideoRef.current.play().catch(() => {
        // ignore autoplay policy errors
      })
      return
    }

    previewVideoRef.current.srcObject = null
  }, [previewStream])

  // Send video frames at adaptive FPS (adjusted by backend target_fps)
  useEffect(() => {
    if (
      !connected ||
      !browserAnalyticsUploadEnabled ||
      !stream ||
      !canvasRef.current ||
      !videoRef.current
    ) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = 480
    canvas.height = 360

    const sendFrame = async () => {
      if (!isVideoEnabled) return
      if (!videoRef.current || videoRef.current.readyState < 2) return
      ctx.drawImage(videoRef.current, 0, 0, 480, 360)
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
  }, [browserAnalyticsUploadEnabled, connected, isVideoEnabled, stream, sendBinary])

  // Stream microphone audio as 16kHz mono PCM in 30ms chunks.
  useEffect(() => {
    if (
      !connected ||
      !browserAnalyticsUploadEnabled ||
      !stream ||
      stream.getAudioTracks().length === 0
    ) return

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
  }, [browserAnalyticsUploadEnabled, connected, stream, sendBinary])

  const isTutor = isTutorRole
  const hasAudioTrack = Boolean(stream?.getAudioTracks().length)
  const hasVideoTrack = Boolean(stream?.getVideoTracks().length)
  const engagementTrendLabel = currentMetrics
    ? currentMetrics.session.engagement_trend === 'rising'
      ? 'Rising'
      : currentMetrics.session.engagement_trend === 'declining'
      ? 'Declining'
      : 'Stable'
    : 'Stable'
  const attentionOverlayState = currentMetrics
    ? currentMetrics.student.instant_attention_state === 'OFF_TASK_AWAY' ||
      currentMetrics.student.instant_attention_state === 'FACE_MISSING' ||
      currentMetrics.student.instant_attention_state === 'DOWN_ENGAGED'
      ? currentMetrics.student.instant_attention_state
      : currentMetrics.student.attention_state
    : null
  const minimalAttentionSummary = currentMetrics && attentionOverlayState
    ? {
        label: 'Student attention',
        value: formatAttentionStateLabel(attentionOverlayState),
        className: attentionPillClasses(attentionOverlayState),
      }
    : null
  const minimalTalkSummary = currentMetrics
    ? talkBalanceSummary(currentMetrics)
    : null
  const minimalFlowSummary = currentMetrics
    ? flowSummary(currentMetrics)
    : null
  const minimalCoachingStatus = currentMetrics
    ? coachingStatusSummary(currentMetrics)
    : null
  const remoteLabel =
    role === 'tutor' ? 'Student' : role === 'student' ? 'Tutor' : 'Participant'
  const localLabel =
    role === 'tutor' ? 'You (Tutor)' : role === 'student' ? 'You (Student)' : 'You'
  const roleBadgeLabel = isTutor
    ? 'Tutor workspace'
    : role === 'student'
    ? 'Student call view'
    : sessionInfoLoaded
    ? 'Preparing join view'
    : 'Preparing session'
  const roleSummaryText = isTutor
    ? 'Live call with private coaching — hidden from students.'
    : role === 'student'
    ? 'Call-focused view. Coaching and analytics are tutor-only.'
    : 'Preparing your session view.'
  const consentButtonLabel = sessionEnded
    ? isTutor
      ? 'View analytics'
      : 'View session'
    : isTutor
    ? 'Join as Tutor'
    : role === 'student'
    ? 'Join as Student'
    : 'Join session'
  const controlTitle = isTutor ? 'Tutor controls' : 'Controls'
  const controlDescription = isTutor
    ? 'Students cannot see your coaching overlay or nudges.'
    : 'Tutor coaching is not visible in student view.'
  const secondaryHelperText = isTutor
    ? 'Open Tutor Debug for session diagnostics.'
    : 'You can rejoin with the same link if you leave.'
  const callPlaceholderText =
    callStatus === 'connected'
      ? `Waiting for ${remoteLabel.toLowerCase()} video.`
      : callStatus === 'connecting'
      ? 'Connecting...'
      : callStatus === 'reconnecting'
      ? 'Reconnecting...'
      : `Waiting for ${remoteLabel.toLowerCase()} to join.`
  const sessionEndedMessage = isTutor
    ? 'Session ended. Analytics are ready.'
    : 'Session complete.'
  const canShowDebugToggle = isTutor || showCoachDebug
  const endSummaryHealth = endSummary ? getSessionHealth(endSummary) : null
  const endSummaryRecommendationsToShow = (
    endSummaryRecommendations.length > 0
      ? endSummaryRecommendations
      : endSummary?.recommendations ?? []
  ).slice(0, 2)
  const showTutorEndSummaryOverlay = sessionEnded && isTutor && showEndSummary

  const stopPreviewTracks = useCallback((streamToStop: MediaStream | null) => {
    streamToStop?.getTracks().forEach((track) => track.stop())
  }, [])

  const startCameraPreview = useCallback(async () => {
    // Stop any existing preview before requesting a new one.
    stopPreviewTracks(previewStreamRef.current)
    previewStreamRef.current = null
    setPreviewStream(null)
    setPreviewError(null)

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 320 }, height: { ideal: 240 } },
        audio: false,
      })
      setPreviewStream(stream)
    } catch {
      setPreviewError('Could not access camera. Please check your permissions.')
    }
  }, [stopPreviewTracks])

  const stopCameraPreview = useCallback(() => {
    stopPreviewTracks(previewStreamRef.current)
    previewStreamRef.current = null
    setPreviewStream(null)
    setPreviewError(null)
  }, [stopPreviewTracks])

  const handleEndSession = useCallback(async () => {
    if (!sessionId || !token || endingSession || sessionEnded) return

    setShowConfirmEnd(false)
    setEndingSession(true)
    setEndSessionError(null)
    appendDebugEvent('manual end session requested')

    try {
      const response = await apiFetch(
        `/api/sessions/${sessionId}/end?token=${encodeURIComponent(token)}`,
        { method: 'POST', accessToken: userAccessToken }
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

  const handleEndedSessionNavigation = useCallback(
    (destination: string) => {
      appendDebugEvent(`leaving ended session view -> ${destination}`)
      clearActiveSession()
      closeConnection('leaving ended session view')
      stopStream()
      router.push(destination)
    },
    [appendDebugEvent, closeConnection, router, stopStream]
  )

  const confirmLeaveSession = useCallback(() => {
    setShowConfirmLeave(false)
    appendDebugEvent('left session locally')
    clearActiveSession()
    closeConnection('left session locally')
    stopStream()
    router.push('/')
  }, [appendDebugEvent, closeConnection, router, stopStream])

  const handleLeaveSession = useCallback(() => {
    if (sessionEnded) {
      handleEndedSessionNavigation(`/analytics/${sessionId}`)
      return
    }
    setShowConfirmLeave(true)
  }, [handleEndedSessionNavigation, sessionEnded, sessionId])

  // ── Camera preview stream: stop tracks on unmount ──
  useEffect(() => {
    return () => {
      stopPreviewTracks(previewStreamRef.current)
      previewStreamRef.current = null
    }
  }, [stopPreviewTracks])

  // ── Close invite menu when clicking outside ──
  useEffect(() => {
    if (!showInviteMenu) return
    const handleClick = (e: MouseEvent) => {
      if (inviteMenuRef.current && !inviteMenuRef.current.contains(e.target as Node)) {
        setShowInviteMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showInviteMenu])

  // ── Session elapsed time counter ──
  useEffect(() => {
    if (sessionStartTime === null) {
      setElapsedSeconds(0)
      return
    }

    // Freeze the timer once the session has ended.
    if (sessionEnded) {
      return
    }

    // Reset on each new session start
    setElapsedSeconds(Math.floor((Date.now() - sessionStartTime) / 1000))
    const id = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - sessionStartTime) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [sessionEnded, sessionStartTime])

  // ── Fullscreen UI: auto-hide controls after inactivity ──
  const [controlsVisible, setControlsVisible] = useState(true)
  const hideTimerRef = useRef<NodeJS.Timeout | null>(null)

  const showControlsTemporarily = useCallback(() => {
    setControlsVisible(true)
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    hideTimerRef.current = setTimeout(() => {
      setControlsVisible(false)
    }, 4000)
  }, [])

  useEffect(() => {
    showControlsTemporarily()
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    }
  }, [showControlsTemporarily])

  // ── Keyboard shortcuts: Space = toggle mute, V = toggle camera ──
  useEffect(() => {
    if (showConsent) return
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeElement = document.activeElement as HTMLElement | null
      const tag = (activeElement?.tagName ?? '').toLowerCase()
      if (
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        activeElement?.isContentEditable
      ) {
        return
      }
      if (e.key === ' ') {
        e.preventDefault()
        showControlsTemporarily()
        toggleAudio()
        appendDebugEvent(isAudioEnabled ? 'mic muted (Space)' : 'mic unmuted (Space)')
      } else if (e.key === 'v' || e.key === 'V') {
        e.preventDefault()
        showControlsTemporarily()
        toggleVideo()
        appendDebugEvent(isVideoEnabled ? 'camera off (V)' : 'camera on (V)')
      } else if (
        (e.key === 't' || e.key === 'T') &&
        (e.ctrlKey || e.metaKey) &&
        isTutor &&
        transcriptionEnabled
      ) {
        e.preventDefault()
        setTranscriptPanelOpen((prev) => !prev)
        appendDebugEvent('transcript panel toggled (Ctrl/Cmd+T)')
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [
    showConsent,
    transcriptionEnabled,
    isTutor,
    toggleAudio,
    toggleVideo,
    isAudioEnabled,
    isVideoEnabled,
    appendDebugEvent,
    showControlsTemporarily,
  ])

  // ── beforeunload guard: warn before closing/navigating away mid-session ──
  // Only active when the session is live (not on consent screen, not ended).
  // Removed automatically once the session ends so analytics navigation isn't blocked.
  useEffect(() => {
    if (showConsent || sessionEnded) return

    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // Setting returnValue is required by some browsers to trigger the dialog
      e.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [showConsent, sessionEnded])

  if (showConsent) {
    return (
      <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(0,102,255,0.2),_transparent_28%),radial-gradient(circle_at_bottom_right,_rgba(255,107,53,0.12),_transparent_32%),#020617] px-6 py-10 text-white">
        <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-5xl items-center justify-center">
          <div className="grid w-full gap-6 rounded-[32px] border border-white/10 bg-slate-950/75 p-6 shadow-[0_28px_120px_rgba(2,6,23,0.6)] backdrop-blur md:grid-cols-[1.1fr_0.9fr] md:p-8">
            <div className="space-y-6">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="rounded-full border border-white/10 bg-white/5 px-3 py-2">
                    <Image
                      src="/nerdy-logo.svg"
                      alt="Nerdy"
                      width={84}
                      height={22}
                      className="h-5 w-auto"
                      priority
                    />
                  </div>
                  <span className="text-xs uppercase tracking-[0.18em] text-slate-500">
                    Varsity Tutors session workspace
                  </span>
                </div>
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
                  <span
                    className="group cursor-pointer rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-400 transition-colors hover:text-slate-200"
                    title={`Session ${sessionId}`}
                    onClick={() => navigator.clipboard.writeText(sessionId)}
                  >
                    {sessionId.slice(0, 8)}…
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

              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <p className="text-xs leading-relaxed text-slate-400">
                  Gaze, speaking time, and engagement are analyzed in real time. No raw audio or video is stored.
                  {transcriptionEnabled && ' Transcripts are generated live but no audio is retained.'}
                </p>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-white/5 p-5 md:p-6">
              <div className="space-y-4">
                <div>
                  <h2 className="text-lg font-semibold text-white">
                    {isTutor
                      ? 'Ready to start'
                      : 'Join session'}
                  </h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Allow camera and microphone access. You can mute after joining.
                  </p>
                </div>

                {/* Camera preview — only shown before joining (not for ended sessions) */}
                {!sessionEnded && (
                  <div className="space-y-2">
                    {previewStream ? (
                      <div className="relative overflow-hidden rounded-2xl bg-black">
                        <video
                          data-testid="camera-preview-video"
                          ref={previewVideoRef}
                          autoPlay
                          muted
                          playsInline
                          className="h-[150px] w-full object-cover"
                        />
                        <button
                          type="button"
                          onClick={stopCameraPreview}
                          className="absolute right-2 top-2 rounded-full border border-white/15 bg-black/60 px-2 py-1 text-[10px] font-medium text-white/80 backdrop-blur-md transition-colors hover:text-white"
                        >
                          Stop preview
                        </button>
                        <div className="absolute bottom-2 left-2 rounded-full border border-white/15 bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-md">
                          Preview
                        </div>
                      </div>
                    ) : (
                      <button
                        data-testid="camera-preview-button"
                        type="button"
                        onClick={() => void startCameraPreview()}
                        className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-white/10 hover:text-white"
                      >
                        Preview camera
                      </button>
                    )}
                    {previewError && (
                      <p className="text-xs text-red-400">{previewError}</p>
                    )}
                  </div>
                )}

                {/* Analysis consent checkbox */}
                {!sessionEnded && (
                  <label
                    data-testid="analysis-consent-label"
                    className="flex cursor-pointer items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.03] p-3.5 transition hover:bg-white/[0.06]"
                  >
                    <input
                      data-testid="analysis-consent-checkbox"
                      type="checkbox"
                      checked={analysisConsent}
                      onChange={(e) => setAnalysisConsent(e.target.checked)}
                      className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer appearance-none rounded border-2 border-white/30 bg-transparent transition checked:border-[#7b6ef6] checked:bg-[#7b6ef6] focus:outline-none focus:ring-2 focus:ring-[#7b6ef6]/40"
                    />
                    <div>
                      <p className="text-sm font-medium leading-snug text-white">
                        I consent to session analysis
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-slate-400">
                        Real-time analysis of engagement signals. No raw audio or video is stored.
                        {transcriptionEnabled && (
                          <span data-testid="transcription-disclosure">
                            {' '}Live transcription is enabled{sessionInfo?.enable_ai_coaching ? ' with AI coaching' : ''}.
                          </span>
                        )}
                      </p>
                    </div>
                  </label>
                )}

                <button
                  data-testid="consent-start-button"
                  disabled={!sessionEnded && !analysisConsent}
                  onClick={() => {
                    if (sessionEnded) {
                      handleLeaveSession()
                      return
                    }
                    // Stop the preview stream before requesting the real stream
                    stopCameraPreview()
                    setShowConsent(false)
                    setSessionStartTime(Date.now())
                    requestAccess()
                  }}
                  className="w-full rounded-2xl bg-gradient-to-r from-[#7b6ef6] to-[#4a90d9] px-4 py-3 text-sm font-medium text-white transition hover:shadow-[0_4px_24px_rgba(123,110,246,0.35)] disabled:cursor-not-allowed disabled:opacity-40"
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
    <div
      data-testid="call-surface"
      className={`fixed inset-0 overflow-hidden bg-black text-white transition-all duration-300 ${
        showCoachDebug ? 'right-[420px] lg:right-[480px]' : ''
      } ${
        isTutor && transcriptionEnabled && transcriptPanelOpen
          ? 'lg:left-[380px]'
          : ''
      }`}
      onMouseMove={showControlsTemporarily}
      onPointerMove={showControlsTemporarily}
      onTouchStart={showControlsTemporarily}
    >
      {/* ── Background layer: remote video / multi-participant grid / local-only ── */}
      {ENABLE_WEBRTC_CALL_UI && remoteParticipants.size > 1 ? (
        <div
          data-testid="participant-grid"
          className={`absolute inset-0 grid gap-1 ${
            remoteParticipants.size === 2
              ? 'grid-cols-2'
              : 'grid-cols-2 grid-rows-2'
          }`}
        >
          {Array.from(remoteParticipants.values())
            .sort(compareParticipantIdentity)
            .map((participant) => (
              <ParticipantTile key={participant.identity} participant={participant} />
            ))}
        </div>
      ) : ENABLE_WEBRTC_CALL_UI ? (
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
              <div
                data-testid="call-status-placeholder"
                className={`rounded-full border px-4 py-1.5 text-xs font-medium ${callStatusClasses(callStatus)}`}
              >
                {callStatusLabel(callStatus)}
              </div>
              <div>
                <p className="text-lg font-medium text-white">{remoteLabel}</p>
                <p className="mt-1 text-sm text-gray-400">{callPlaceholderText}</p>
              </div>
              {ENABLE_WEBRTC_CALL_UI && !hasRemoteAudio && callStatus === 'connected' && (
                <p className="text-xs text-gray-500">Remote audio not detected yet.</p>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="absolute inset-0 h-full w-full object-cover"
          />
          {!isVideoEnabled && hasVideoTrack && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/75 text-sm text-gray-200">
              Camera is off
            </div>
          )}
        </>
      )}

      <canvas ref={canvasRef} className="hidden" />

      {/* ── Persistent ended-session navigation bar (always visible when session is over) ── */}
      {sessionEnded && (
        <div
          data-testid="ended-session-nav-bar"
          className="pointer-events-auto absolute left-0 right-0 top-0 z-30 flex min-h-10 items-center justify-between gap-3 bg-black/80 px-4 py-2 backdrop-blur-md"
        >
          <span className="whitespace-nowrap text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
            Session ended
          </span>
          <div className="flex items-center gap-2 overflow-x-auto">
            <button
              data-testid="ended-nav-view-analytics"
              type="button"
              onClick={() => handleEndedSessionNavigation(`/analytics/${sessionId}`)}
              className="whitespace-nowrap rounded-full bg-violet-600 px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-violet-500"
            >
              View Analytics
            </button>
            <button
              data-testid="ended-nav-dashboard"
              type="button"
              onClick={() => handleEndedSessionNavigation('/')}
              className="whitespace-nowrap rounded-full border border-white/15 bg-white/5 px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/10"
            >
              Back to Dashboard
            </button>
          </div>
        </div>
      )}

      {/* ── Top bar overlay (auto-hide after 4s inactivity) ── */}
      <div
        className={`pointer-events-none absolute left-0 right-0 z-20 transition-opacity duration-500 ${
          sessionEnded ? 'top-10' : 'top-0'
        } ${
          controlsVisible ? 'pointer-events-auto opacity-100' : 'opacity-0'
        }`}
      >
        <div className="flex items-center justify-between bg-gradient-to-b from-black/70 to-transparent px-4 py-3">
          {/* Left: connection status dot + role badge + session ID + call status */}
          <div className="flex flex-wrap items-center gap-2">
            <div
              className={`h-2.5 w-2.5 flex-shrink-0 rounded-full ${
                connected ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <span
              data-testid="session-role-badge"
              className={`rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] backdrop-blur-md ${
                isTutor
                  ? 'border-sky-400/40 bg-sky-500/10 text-sky-100'
                  : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
              }`}
            >
              {roleBadgeLabel}
            </span>
            <button
              type="button"
              aria-label="Copy session ID"
              className="rounded-full border border-white/10 bg-black/40 px-3 py-1 text-[11px] text-slate-300 backdrop-blur-md transition-colors hover:text-slate-100"
              title={`Session ${sessionId}`}
              onClick={() => navigator.clipboard.writeText(sessionId)}
            >
              {sessionId.slice(0, 8)}…
            </button>
            {sessionStartTime !== null && !sessionEnded && (
              <div
                data-testid="session-elapsed-timer"
                className="rounded-full border border-white/10 bg-black/40 px-3 py-1 font-mono text-[11px] tabular-nums text-slate-300 backdrop-blur-md"
                aria-label={`Elapsed time: ${formatElapsed(elapsedSeconds)}`}
              >
                {formatElapsed(elapsedSeconds)}
              </div>
            )}
            <div
              data-testid="call-status-badge"
              className={`rounded-full border px-3 py-1 text-[11px] font-medium backdrop-blur-md ${callStatusClasses(callStatus)}`}
            >
              {callStatusLabel(callStatus)}
            </div>
            {peerDisconnected && !sessionEnded && (
              <div className="rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1 text-[11px] font-medium text-amber-100 backdrop-blur-md">
                Reconnect grace active
              </div>
            )}
          </div>
          {/* Right: latency info + invite button + debug toggle */}
          <div className="flex items-center gap-2">
            {showCoachDebug && currentMetrics && (
              <span className="text-xs text-gray-400">
                p50: {currentMetrics.latency_p50_ms.toFixed(0)}ms · p95:{' '}
                {currentMetrics.latency_p95_ms.toFixed(0)}ms
                {currentMetrics.degraded && (
                  <span className="ml-2 text-yellow-400">
                    DEGRADED ({currentMetrics.degradation_reason})
                  </span>
                )}
                {(currentMetrics.backpressure_level ?? 0) >= 3 && (
                  <span className="ml-2 text-red-400">
                    Transcription unavailable
                  </span>
                )}
                {(currentMetrics.backpressure_level ?? 0) === 2 && (
                  <span className="ml-2 text-yellow-400">
                    Transcription degraded
                  </span>
                )}
              </span>
            )}
            {/* Invite student button — tutor only, only while session is live */}
            {isTutor && !sessionEnded && sessionInfo?.student_tokens && sessionInfo.student_tokens.length > 0 && (
              <div ref={inviteMenuRef} className="relative">
                {sessionInfo.student_tokens.length === 1 ? (
                  <button
                    data-testid="invite-student-button"
                    type="button"
                    onClick={() => {
                      const url = buildStudentInviteUrl(
                        sessionId,
                        sessionInfo.student_tokens![0]
                      )
                      copyToClipboard(url)
                        .then(() => toast.success('Student invite link copied!'))
                        .catch(() => toast.error('Failed to copy link'))
                    }}
                    className="flex items-center gap-1.5 rounded-full border border-white/20 bg-black/40 px-3 py-1 text-xs font-medium text-gray-200 backdrop-blur-md transition-colors hover:bg-black/60 hover:text-white"
                    title="Copy student invite link"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    >
                      <path d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z" />
                      <path d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z" />
                    </svg>
                    Invite student
                  </button>
                ) : (
                  <>
                    <button
                      data-testid="invite-student-button"
                      type="button"
                      onClick={() => setShowInviteMenu((prev) => !prev)}
                      className="flex items-center gap-1.5 rounded-full border border-white/20 bg-black/40 px-3 py-1 text-xs font-medium text-gray-200 backdrop-blur-md transition-colors hover:bg-black/60 hover:text-white"
                      title="Copy a student invite link"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="h-3.5 w-3.5"
                        aria-hidden="true"
                      >
                        <path d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z" />
                        <path d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z" />
                      </svg>
                      Invite student
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="h-3 w-3"
                        aria-hidden="true"
                      >
                        <path
                          fillRule="evenodd"
                          d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </button>
                    {showInviteMenu && (
                      <div className="absolute right-0 top-full mt-1 min-w-[160px] rounded-xl border border-white/15 bg-black/85 py-1 shadow-lg backdrop-blur-md">
                        {sessionInfo.student_tokens.map((studentToken, idx) => (
                          <button
                            key={studentToken}
                            type="button"
                            onClick={() => {
                              const url = buildStudentInviteUrl(sessionId, studentToken)
                              copyToClipboard(url)
                                .then(() => {
                                  toast.success(`Student ${idx + 1} invite link copied!`)
                                  setShowInviteMenu(false)
                                })
                                .catch(() => toast.error('Failed to copy link'))
                            }}
                            className="flex w-full items-center gap-2 px-4 py-2 text-xs text-gray-200 transition-colors hover:bg-white/10 hover:text-white"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              viewBox="0 0 20 20"
                              fill="currentColor"
                              className="h-3.5 w-3.5 flex-shrink-0 text-gray-400"
                              aria-hidden="true"
                            >
                              <path d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z" />
                              <path d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z" />
                            </svg>
                            Copy Student {idx + 1} link
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
            {canShowDebugToggle && (
              <button
                data-testid="coach-debug-toggle"
                type="button"
                onClick={() => setShowCoachDebug((prev) => !prev)}
                className={`rounded-full border px-3 py-1 text-xs font-medium backdrop-blur-md transition-colors ${
                  showCoachDebug
                    ? 'border-blue-400/50 bg-blue-500/20 text-blue-100'
                    : 'border-white/20 bg-black/40 text-gray-200 hover:bg-black/60'
                }`}
              >
                {showCoachDebug ? 'Hide debug' : isTutor ? 'Tutor Debug' : 'Debug'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Coach overlay pills — always visible, top-left below top bar ── */}
      {isTutor && currentMetrics && minimalAttentionSummary && minimalTalkSummary && minimalFlowSummary && (
        <div
          data-testid="coach-overlay"
          className="pointer-events-none absolute left-3 right-3 top-14 z-10 flex flex-wrap items-start gap-2"
        >
          {[
            minimalAttentionSummary,
            minimalTalkSummary,
            minimalFlowSummary,
            ...(minimalCoachingStatus ? [minimalCoachingStatus] : []),
          ].map((pill) => (
            <div
              key={pill.label}
              data-testid={pill.label === 'Coaching' ? 'coaching-status-pill' : undefined}
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

      {/* ── Uncertainty indicator overlay (tutor-only, near student video) ── */}
      {isTutor && transcriptionEnabled && uncertainty.visible && (
        <div
          data-testid="uncertainty-indicator"
          className={`pointer-events-none absolute right-4 top-14 z-10 transition-opacity duration-500 ${
            uncertainty.visible ? 'opacity-100' : 'opacity-0'
          }`}
        >
          <div className="rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium tracking-[0.02em] text-amber-100 shadow-[0_0_22px_rgba(245,158,11,0.16)] backdrop-blur-md">
            <span className="mr-2 text-[10px] uppercase tracking-[0.16em] text-white/55">
              Uncertainty
            </span>
            <span>
              {uncertainty.topic || 'Detected'}
              {uncertainty.score !== null && (
                <span className="ml-1.5 text-[10px] tabular-nums text-amber-300/70">
                  {Math.round(uncertainty.score * 100)}%
                </span>
              )}
            </span>
          </div>
        </div>
      )}

      {/* ── Detailed metrics overlay (debug only) ── */}
      {showCoachDebug && isTutor && currentMetrics && (
        <div className="absolute left-3 right-3 top-28 z-10 rounded-2xl border border-white/10 bg-black/55 p-3 text-xs text-white backdrop-blur-md">
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
              {(() => {
                const sessionType = sessionInfo?.session_type ?? currentMetrics?.coaching_decision?.session_type ?? 'general'
                const target = getTutorTalkTarget(sessionType)
                const tutorPct = currentMetrics.tutor.talk_time_percent
                const isOver = tutorPct > target + 0.12
                return (
                  <>
                    <div className="mb-0.5 flex justify-between text-[10px]">
                      <span className={isOver ? 'text-amber-400' : ''}>
                        Talk share · Tutor {(tutorPct * 100).toFixed(0)}%
                      </span>
                      <span>
                        Student {(currentMetrics.student.talk_time_percent * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="relative">
                      <div className="flex h-2 overflow-hidden rounded-full bg-gray-600">
                        <div
                          className={`h-full transition-all duration-300 ${isOver ? 'bg-amber-400' : 'bg-blue-400'}`}
                          style={{ width: `${tutorPct * 100}%` }}
                        />
                        <div
                          className="h-full bg-green-400 transition-all duration-300"
                          style={{ width: `${currentMetrics.student.talk_time_percent * 100}%` }}
                        />
                      </div>
                      {/* Target marker */}
                      <div
                        className="absolute top-[-3px] h-[14px] w-[2px] rounded-full bg-white/70"
                        style={{ left: `${target * 100}%` }}
                        title={`Target tutor share: ${(target * 100).toFixed(0)}%`}
                      />
                      <div
                        className="absolute top-[-12px] text-[8px] font-medium text-white/50"
                        style={{ left: `${target * 100}%`, transform: 'translateX(-50%)' }}
                      >
                        {(target * 100).toFixed(0)}%
                      </div>
                    </div>
                  </>
                )
              })()}
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

      {/* ── Local video PIP (bottom-right, above bottom control bar) ── */}
      {ENABLE_WEBRTC_CALL_UI && (
        <div data-testid="local-video-pip" className="absolute bottom-24 right-4 z-10 w-[360px] overflow-hidden rounded-2xl border border-white/15 bg-black/80 shadow-lg sm:w-[480px]">
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
          <div className="absolute bottom-2 left-2 rounded-full border border-white/10 bg-black/55 px-2 py-0.5 text-xs font-medium text-white backdrop-blur-md">
            {localLabel}
          </div>
        </div>
      )}

      {/* ── Bottom control bar (auto-hide after 4s inactivity) ── */}
      <div
        data-testid="controls-overlay"
        className={`pointer-events-none absolute bottom-0 left-0 right-0 z-20 transition-opacity duration-500 ${
          controlsVisible ? 'pointer-events-auto opacity-100' : 'opacity-0'
        }`}
      >
        <div className="flex items-center justify-center gap-4 bg-gradient-to-t from-black/70 to-transparent px-4 pb-6 pt-8">
          {/* Mute mic — icon-based circular button */}
          <button
            data-testid="mute-button"
            type="button"
            aria-label={isAudioEnabled ? 'Mute microphone' : 'Unmute microphone'}
            onClick={() => {
              toggleAudio()
              appendDebugEvent(isAudioEnabled ? 'microphone muted locally' : 'microphone unmuted locally')
            }}
            disabled={!hasAudioTrack}
            title={isAudioEnabled ? 'Mute microphone (Space)' : 'Unmute microphone (Space)'}
            className={`flex h-12 w-12 items-center justify-center rounded-full border backdrop-blur-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-50 ${
              isAudioEnabled
                ? 'border-white/20 bg-white/10 text-white hover:bg-white/20'
                : 'border-red-500/60 bg-red-600/80 text-white hover:bg-red-500'
            }`}
          >
            {isAudioEnabled ? <MicIcon /> : <MicOffIcon />}
          </button>

          {/* Toggle camera — icon-based circular button */}
          <button
            data-testid="camera-button"
            type="button"
            aria-label={isVideoEnabled ? 'Turn camera off' : 'Turn camera on'}
            onClick={() => {
              toggleVideo()
              appendDebugEvent(isVideoEnabled ? 'camera turned off locally' : 'camera turned on locally')
            }}
            disabled={!hasVideoTrack}
            title={isVideoEnabled ? 'Turn camera off (V)' : 'Turn camera on (V)'}
            className={`flex h-12 w-12 items-center justify-center rounded-full border backdrop-blur-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-50 ${
              isVideoEnabled
                ? 'border-white/20 bg-white/10 text-white hover:bg-white/20'
                : 'border-red-500/60 bg-red-600/80 text-white hover:bg-red-500'
            }`}
          >
            {isVideoEnabled ? <CameraIcon /> : <CameraOffIcon />}
          </button>

          {/* Transcript toggle (tutor, transcription enabled) */}
          {isTutor && transcriptionEnabled && (
            <button
              data-testid="transcript-toggle-button"
              type="button"
              aria-label={transcriptPanelOpen ? 'Hide transcript (Ctrl+T)' : 'Show transcript (Ctrl+T)'}
              onClick={() => setTranscriptPanelOpen((prev) => !prev)}
              title={transcriptPanelOpen ? 'Hide transcript (Ctrl+T)' : 'Show transcript (Ctrl+T)'}
              className={`flex h-12 items-center justify-center rounded-full border backdrop-blur-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 ${
                transcriptPanelOpen
                  ? 'border-sky-400/50 bg-sky-500/20 px-4 text-sky-100'
                  : 'w-12 border-white/20 bg-white/10 text-white hover:bg-white/20'
              }`}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-5 w-5"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M4.5 2A2.5 2.5 0 0 0 2 4.5v11A2.5 2.5 0 0 0 4.5 18h11a2.5 2.5 0 0 0 2.5-2.5v-11A2.5 2.5 0 0 0 15.5 2h-11ZM5 5.75A.75.75 0 0 1 5.75 5h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 5.75Zm0 3A.75.75 0 0 1 5.75 8h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 8.75Zm0 3A.75.75 0 0 1 5.75 11h5.5a.75.75 0 0 1 0 1.5h-5.5A.75.75 0 0 1 5 11.75Z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          )}

          {/* AI Suggest button + card anchor (tutor, transcription enabled) */}
          {isTutor && transcriptionEnabled && !sessionEnded && (
            <div className="relative">
              {/* Suggestion card anchored above the button */}
              {(activeAISuggestion || aiSuggestionLoading) && (
                <div
                  data-testid="ai-suggestion-overlay"
                  className="absolute bottom-full right-1/2 translate-x-1/2 mb-3 w-[360px] max-w-[calc(100vw-2rem)] z-30"
                >
                  <AISuggestionCard
                    suggestion={activeAISuggestion}
                    loading={aiSuggestionLoading}
                    onDismiss={() => {
                      clearSuggestion()
                      clearAiSuggestionFromNudge()
                    }}
                    onFeedback={(suggestionId, helpful) => {
                      void submitSuggestionFeedback(suggestionId, helpful)
                    }}
                  />
                </div>
              )}
              <SuggestButton
                loading={aiSuggestionLoading}
                onClick={() => void requestSuggestion()}
                callsRemaining={aiCallsRemaining}
              />
            </div>
          )}

          {/* End session (tutor) — red circular button */}
          {isTutor && (
            <button
              data-testid="end-session-button"
              type="button"
              aria-label={sessionEnded ? 'Session ended' : 'End session for everyone'}
              onClick={() => setShowConfirmEnd(true)}
              disabled={endingSession || sessionEnded}
              title={sessionEnded ? 'Session ended' : 'End session for everyone'}
              className="flex h-12 w-12 items-center justify-center rounded-full border border-red-500/60 bg-red-600 text-white backdrop-blur-md transition-colors hover:bg-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <PhoneOffIcon />
            </button>
          )}

          {/* Leave session (student) — red circular button */}
          {!isTutor && (
            <button
              data-testid="leave-session-button"
              type="button"
              aria-label={sessionEnded ? 'View your session' : 'Leave session'}
              onClick={handleLeaveSession}
              title={sessionEnded ? 'View your session' : 'Leave session'}
              className="flex h-12 w-12 items-center justify-center rounded-full border border-red-500/60 bg-red-600 text-white backdrop-blur-md transition-colors hover:bg-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            >
              <PhoneOffIcon />
            </button>
          )}

          {/* Tutor post-session navigation (when session ended and summary dismissed) */}
          {isTutor && sessionEnded && !showTutorEndSummaryOverlay && (
            <>
              <button
                data-testid="view-analytics-button"
                type="button"
                onClick={() => handleEndedSessionNavigation(`/analytics/${sessionId}`)}
                className="rounded-full border border-white/20 bg-black/50 px-4 py-2 text-sm font-medium text-white backdrop-blur-md transition-colors hover:bg-black/70"
              >
                View analytics
              </button>
              <button
                type="button"
                onClick={() => handleEndedSessionNavigation('/')}
                className="rounded-full border border-white/10 bg-black/40 px-4 py-2 text-sm font-medium text-white backdrop-blur-md transition-colors hover:bg-black/60"
              >
                Dashboard
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Session banners (pinned near top, below top bar) ── */}
      {peerDisconnected && !sessionEnded && (
        <div
          data-testid="participant-disconnected-banner"
          className="absolute left-4 right-4 top-16 z-30 rounded-2xl border border-yellow-700 bg-yellow-900/80 p-3 text-sm text-yellow-100 backdrop-blur-md"
        >
          {remoteLabel} disconnected. They can rejoin within the grace window, and the call will attempt to recover automatically.
        </div>
      )}

      {sessionEnded && !isTutor && (
        <div
          data-testid="session-ended-banner"
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
        >
          <div className="mx-4 w-full max-w-md rounded-2xl border border-white/10 bg-[#1e2545] p-8 text-center shadow-2xl">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-500/20">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-6 w-6 text-blue-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-white">Session complete</h2>
            <p className="mt-2 text-sm leading-6 text-[#8896b3]">{sessionEndedMessage}</p>
            <p className="mt-4 text-xs text-[#556080]">Redirecting to your dashboard…</p>
            <button
              type="button"
              onClick={() => { closeConnection('student left'); stopStream(); router.push('/') }}
              className="mt-4 rounded-xl bg-gradient-to-r from-[#7b6ef6] to-[#4a90d9] px-6 py-2 text-sm font-medium text-white transition hover:shadow-lg"
            >
              Go now
            </button>
          </div>
        </div>
      )}

      {/* ── Nudge toasts (tutor only) — positioned above PIP, inside call surface ── */}
      {isTutor && nudges.length > 0 && (
        <div className="pointer-events-none absolute inset-0 z-20">
          <div className="pointer-events-auto absolute bottom-[340px] right-4 w-[380px] max-w-[calc(100%-2rem)] space-y-3 sm:bottom-[420px] sm:w-[420px]">
            {nudges.map((nudge) => {
              const isHigh = nudge.priority === 'high'
              const isMed = nudge.priority === 'medium'
              return (
                <div
                  key={nudge.id}
                  className={`animate-slide-in-right rounded-2xl border-2 p-4 shadow-2xl backdrop-blur-md ${
                    isHigh
                      ? 'border-red-500/60 bg-red-950/95 shadow-red-900/40'
                      : isMed
                      ? 'border-amber-500/50 bg-amber-950/95 shadow-amber-900/30'
                      : 'border-blue-500/40 bg-slate-900/95 shadow-blue-900/20'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Icon dot */}
                    <div className={`mt-1 h-3 w-3 flex-shrink-0 rounded-full ${
                      isHigh ? 'bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.6)]' : isMed ? 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.5)]' : 'bg-blue-400 shadow-[0_0_8px_rgba(96,165,250,0.5)]'
                    }`} />
                    <div className="flex-1 min-w-0">
                      {/* Label */}
                      <div className={`mb-0.5 text-[10px] font-bold uppercase tracking-wider ${
                        isHigh ? 'text-red-400' : isMed ? 'text-amber-400' : 'text-blue-400'
                      }`}>
                        {isHigh ? 'Action needed' : isMed ? 'Coaching tip' : 'Suggestion'}
                      </div>
                      {/* Message */}
                      <p className="text-sm font-medium leading-snug text-white">{nudge.message}</p>
                    </div>
                    {/* Close X */}
                    <button
                      type="button"
                      onClick={() => dismissNudge(nudge.id)}
                      className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-sm text-white/40 transition hover:bg-white/10 hover:text-white"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="mt-2.5 flex items-center gap-2 border-t border-white/10 pt-2.5">
                    <button
                      type="button"
                      onClick={() => dismissNudge(nudge.id)}
                      className="rounded-full bg-white/10 px-3.5 py-1 text-xs font-semibold text-white transition hover:bg-white/20"
                    >
                      Got it
                    </button>
                    <button
                      type="button"
                      onClick={disableAllNudges}
                      className="ml-auto rounded-full px-3 py-1 text-[10px] text-white/30 transition hover:text-white/50"
                    >
                      Pause nudges
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {isTutor && !nudgesEnabled && (
        <div className="absolute bottom-[340px] right-4 z-20 sm:bottom-[420px]">
          <button
            type="button"
            onClick={enableAllNudges}
            className="rounded-full border border-white/10 bg-gray-900/90 px-3 py-2 text-xs text-gray-200 shadow-lg transition hover:bg-gray-800/90 hover:text-white"
          >
            Nudges paused · <span className="underline">Resume</span>
          </button>
        </div>
      )}

      {/* ── Errors ── */}
      {(mediaError || wsError || peerError || endSessionError) && (
        <div className="absolute bottom-24 left-4 z-30 max-w-sm rounded-2xl border border-red-700 bg-red-900/80 p-3 text-sm text-white backdrop-blur-md">
          {mediaError && <p>Media: {mediaError}</p>}
          {wsError && <p>Connection: {wsError}</p>}
          {peerError && <p>WebRTC: {peerError}</p>}
          {endSessionError && <p>Session: {endSessionError}</p>}
        </div>
      )}

      {/* ── Tutor Debug — slide-in drawer from the right ── */}
      {showCoachDebug && (
        <div
          data-testid="coach-debug-panel"
          className="fixed bottom-0 right-0 top-0 z-40 w-[420px] overflow-y-auto border-l border-white/10 bg-[#111627]/98 backdrop-blur-md lg:w-[480px]"
        >
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/10 bg-[#111627] px-4 py-3">
            <span className="text-sm font-semibold text-white">Tutor Debug</span>
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
                onClick={toggleNudgeSound}
                className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white transition-colors hover:bg-white/10"
              >
                {nudgeSoundEnabled ? 'Mute chime' : 'Unmute chime'}
              </button>
              <button
                type="button"
                onClick={() => setShowCoachDebug(false)}
                className="rounded-full border border-white/15 bg-white/5 px-2 py-1 text-xs text-white transition-colors hover:bg-white/10"
              >
                ✕
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-4 px-4 py-4 text-sm">
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
                <p>Nudge chime enabled: {nudgeSoundEnabled ? 'yes' : 'no'}</p>
                <p data-testid="debug-media-provider">Media provider: {mediaProvider}</p>
                <p data-testid="debug-analytics-ingest-mode">Analytics ingest: {analyticsIngestMode}</p>
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
                  <p>Student live attention: {formatAttentionStateLabel(currentMetrics.student.instant_attention_state)}</p>
                  <p>Student live attention confidence: {(currentMetrics.student.instant_attention_state_confidence * 100).toFixed(1)}%</p>
                  <p>Student smoothed attention state: {formatAttentionStateLabel(currentMetrics.student.attention_state)}</p>
                  <p>Student attention confidence: {(currentMetrics.student.attention_state_confidence * 100).toFixed(1)}%</p>
                  <p>Student face presence: {(currentMetrics.student.face_presence_score * 100).toFixed(1)}%</p>
                  <p>Student visual attention score: {(currentMetrics.student.visual_attention_score * 100).toFixed(1)}%</p>
                  <p>Student camera-facing score: {(currentMetrics.student.eye_contact_score * 100).toFixed(1)}%</p>
                  <p>Tutor live attention: {formatAttentionStateLabel(currentMetrics.tutor.instant_attention_state)}</p>
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
                  <p>Latency p50: {currentMetrics.latency_p50_ms.toFixed(1)}ms</p>
                  <p>Latency p95: {currentMetrics.latency_p95_ms.toFixed(1)}ms</p>
                  <p>Degradation: {currentMetrics.degradation_reason}</p>
                  <p>Student time in state: {currentMetrics.student.time_in_attention_state_seconds.toFixed(0)}s</p>
                  <p>Student talk (windowed): {(currentMetrics.student.talk_time_pct_windowed * 100).toFixed(1)}%</p>
                  <p>Tutor talk (windowed): {(currentMetrics.tutor.talk_time_pct_windowed * 100).toFixed(1)}%</p>
                  <p>Student time since spoke: {currentMetrics.student.time_since_spoke_seconds.toFixed(1)}s</p>
                  <p>Tutor time since spoke: {currentMetrics.tutor.time_since_spoke_seconds.toFixed(1)}s</p>
                </div>
              ) : (
                <p data-testid="debug-no-live-metrics" className="text-gray-400">No live metrics yet.</p>
              )}
            </div>

            <div className="space-y-2">
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
              <h3 className="font-semibold text-white">Coaching decisions</h3>
              {currentMetrics?.coaching_decision ? (
                <div data-testid="debug-coaching-decision" className="space-y-2 rounded bg-gray-900 p-3 text-xs text-gray-300">
                  <p>
                    <span className="text-gray-500">Session type:</span>{' '}
                    {currentMetrics.coaching_decision.session_type}
                  </p>
                  {(currentMetrics.coaching_decision.coaching_intensity ?? sessionInfo?.coaching_intensity) ? (
                    <p>
                      <span className="text-gray-500">Coaching intensity:</span>{' '}
                      {currentMetrics.coaching_decision.coaching_intensity ?? sessionInfo?.coaching_intensity}
                    </p>
                  ) : null}
                  {currentMetrics.coaching_decision.candidates_evaluated !== undefined && (
                    <details className="cursor-pointer">
                      <summary className="text-gray-400">
                        Rules evaluated: {currentMetrics.coaching_decision.candidates_evaluated.length}
                      </summary>
                      <ul className="ml-4 mt-1 list-disc text-gray-500">
                        {currentMetrics.coaching_decision.candidates_evaluated.map((name, i) => (
                          <li key={i}>{name}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {currentMetrics.coaching_decision.fired_rule !== undefined ? (
                    currentMetrics.coaching_decision.fired_rule ? (
                      <p>
                        <span className="text-green-400">▶ Fired rule:</span>{' '}
                        <span className="text-green-300">{currentMetrics.coaching_decision.fired_rule}</span>
                        {currentMetrics.coaching_decision.fired_rule_score != null && (
                          <span className="ml-2 text-xs text-green-200">
                            score {currentMetrics.coaching_decision.fired_rule_score.toFixed(2)}
                          </span>
                        )}
                        {currentMetrics.coaching_decision.emitted_priority && (
                          <span className="ml-2 text-xs text-amber-200">
                            {currentMetrics.coaching_decision.emitted_priority}
                          </span>
                        )}
                      </p>
                    ) : (
                      <p className="text-gray-500">No rule fired</p>
                    )
                  ) : currentMetrics.coaching_decision.emitted_nudge ? (
                    <p>
                      <span className="text-green-400">▶ Fired:</span>{' '}
                      {currentMetrics.coaching_decision.emitted_nudge}
                    </p>
                  ) : (
                    <p className="text-gray-500">No nudge fired this cycle</p>
                  )}
                  {currentMetrics.coaching_decision.candidate_nudges.length > 0 && (
                    <div>
                      <p>
                        <span className="text-yellow-400">Candidates:</span>{' '}
                        {currentMetrics.coaching_decision.candidate_nudges.join(', ')}
                      </p>
                      {currentMetrics.coaching_decision.candidate_rule_scores && (
                        <ul className="ml-4 mt-1 list-disc text-gray-500">
                          {Object.entries(currentMetrics.coaching_decision.candidate_rule_scores).map(([rule, score]) => (
                            <li key={rule}>{rule}: {score.toFixed(2)}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                  {currentMetrics.coaching_decision.suppressed_reasons.length > 0 && (
                    <div>
                      <span className="text-gray-400">Suppressed:</span>
                      <ul className="ml-4 list-disc">
                        {currentMetrics.coaching_decision.suppressed_reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {Object.keys(currentMetrics.coaching_decision.trigger_features).length > 0 && (
                    <details className="cursor-pointer">
                      <summary className="text-gray-400">Trigger features</summary>
                      <pre className="mt-1 whitespace-pre-wrap break-words text-gray-500">
                        {JSON.stringify(currentMetrics.coaching_decision.trigger_features, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ) : (
                <p className="text-gray-500 text-xs">No coaching decisions yet (waiting for warmup).</p>
              )}
            </div>

            <div className="space-y-2">
              <h3 className="font-semibold text-white">Raw snapshot</h3>
              <pre className="max-h-40 overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-300 whitespace-pre-wrap break-words">
                {currentMetrics ? JSON.stringify(currentMetrics, null, 2) : 'No metrics yet.'}
              </pre>
            </div>

            <div className="space-y-2">
              <h3 className="font-semibold text-white">History</h3>
              <p className="text-xs text-gray-400">
                Metrics snapshots kept in memory: {metricsHistory.length}. Live nudge history: {nudgeHistory.length}.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Transcript panel sidebar (tutor only, left side) ── */}
      {isTutor && transcriptionEnabled && transcriptPanelOpen && (
        <div
          data-testid="transcript-sidebar"
          className="fixed inset-y-0 left-0 z-40 flex w-full max-w-[320px] flex-col border-r border-white/10 bg-[#111627]/98 backdrop-blur-md sm:w-[320px] lg:w-[380px] lg:max-w-none"
        >
          <TranscriptPanel
            messages={transcriptMessages}
            viewerRole="tutor"
          />
        </div>
      )}

      {/* AI Suggestion Card is now anchored above the suggest button in the control bar */}

      {/* ── Confirm Leave modal ── */}
      {showConfirmLeave && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-[#1e2545] p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-white">Leave session?</h3>
            <p className="mt-2 text-sm leading-6 text-[#8896b3]">
              You can rejoin later with the same link. The session will stay active for other participants.
            </p>
            <div className="mt-5 flex gap-3">
              <button
                type="button"
                onClick={() => setShowConfirmLeave(false)}
                className="flex-1 rounded-xl border border-white/10 bg-white/5 py-2.5 text-sm font-medium text-white transition hover:bg-white/10"
              >
                Stay
              </button>
              <button
                type="button"
                onClick={confirmLeaveSession}
                className="flex-1 rounded-xl bg-rose-600 py-2.5 text-sm font-medium text-white transition hover:bg-rose-500"
              >
                Leave
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Confirm End Session modal ── */}
      {showConfirmEnd && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-white/10 bg-[#1e2545] p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-white">End session for everyone?</h3>
            <p className="mt-2 text-sm leading-6 text-[#8896b3]">
              This will end the call for all participants and generate the analytics report. This cannot be undone.
            </p>
            <div className="mt-5 flex gap-3">
              <button
                type="button"
                onClick={() => setShowConfirmEnd(false)}
                className="flex-1 rounded-xl border border-white/10 bg-white/5 py-2.5 text-sm font-medium text-white transition hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleEndSession()}
                className="flex-1 rounded-xl bg-rose-600 py-2.5 text-sm font-medium text-white transition hover:bg-rose-500"
              >
                End Session
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── End-session summary overlay (unchanged) ── */}
      {showTutorEndSummaryOverlay && (
        <div
          data-testid="session-end-summary-overlay"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/95 px-6 py-8 backdrop-blur"
        >
          <div className="w-full max-w-5xl rounded-[32px] border border-white/10 bg-slate-950/95 p-6 shadow-[0_28px_120px_rgba(2,6,23,0.72)] md:p-8">
            <div className="flex flex-col gap-4 border-b border-white/10 pb-6 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                  Session wrap-up
                </p>
                <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">
                  Session Complete
                </h2>
                {endSummary && endSummaryHealth && (
                  <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
                    <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-slate-200">
                      Duration {formatMinutes(endSummary.duration_seconds)}
                    </span>
                    <span
                      className={`rounded-full border px-3 py-1 ${analyticsToneClasses(
                        endSummaryHealth.tone
                      )}`}
                    >
                      {endSummaryHealth.label}
                    </span>
                  </div>
                )}
              </div>
              <button
                data-testid="session-end-summary-close"
                type="button"
                onClick={() => setShowEndSummary(false)}
                className="self-start rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                Close
              </button>
            </div>

            {(endSummaryLoading || (!endSummary && !endSummaryFailed)) && (
              <div
                data-testid="session-end-summary-loading"
                className="flex min-h-[280px] flex-col items-center justify-center gap-4 text-center"
              >
                <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-700 border-t-sky-400" />
                <div>
                  <p className="text-lg font-medium text-white">
                    Generating session report...
                  </p>
                  <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                    We&apos;re packaging the final analytics summary so you can move straight from the call into review.
                  </p>
                </div>
              </div>
            )}

            {!endSummaryLoading && endSummary && endSummaryHealth && (
              <div className="space-y-8 pt-8">
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <MetricCard
                    title="Engagement score"
                    value={formatScore(endSummary.engagement_score)}
                    detail={endSummaryHealth.summary}
                    tone={endSummaryHealth.tone}
                  />
                  <MetricCard
                    title="Student camera-facing"
                    value={formatPercent(endSummary.avg_eye_contact.student || 0)}
                    detail="Average presence across the full session."
                    tone={
                      (endSummary.avg_eye_contact.student || 0) >= 0.5
                        ? 'emerald'
                        : (endSummary.avg_eye_contact.student || 0) >= 0.3
                        ? 'amber'
                        : 'rose'
                    }
                  />
                  <MetricCard
                    title="Tutor talk share"
                    value={formatPercent(endSummary.talk_time_ratio.tutor || 0)}
                    detail={
                      isTalkBalanced(endSummary)
                        ? 'Talk balance stayed near the session target.'
                        : 'Talk balance drifted outside the session target.'
                    }
                    tone={
                      isTalkBalanced(endSummary)
                        ? 'emerald'
                        : (endSummary.talk_time_ratio.tutor || 0) >= 0.8
                        ? 'rose'
                        : 'amber'
                    }
                  />
                  <MetricCard
                    title="Interruptions"
                    value={`${endSummary.total_interruptions}`}
                    detail={
                      endSummary.total_interruptions === 0
                        ? 'No interruptions were flagged.'
                        : 'Counted across the entire session.'
                    }
                    tone={
                      endSummary.total_interruptions >= 5
                        ? 'rose'
                        : endSummary.total_interruptions >= 2
                        ? 'amber'
                        : 'emerald'
                    }
                  />
                </div>

                <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
                  <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Quick highlights
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {endSummary.flagged_moments.length > 0 ? (
                        <span className="rounded-full border border-rose-400/30 bg-rose-400/10 px-3 py-1.5 text-sm font-medium text-rose-100">
                          {endSummary.flagged_moments.length} flagged moment
                          {endSummary.flagged_moments.length === 1 ? '' : 's'}
                        </span>
                      ) : (
                        <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-sm font-medium text-emerald-100">
                          No flagged moments surfaced
                        </span>
                      )}
                      {endSummary.nudges_sent > 0 && (
                        <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1.5 text-sm font-medium text-amber-100">
                          {endSummary.nudges_sent} live nudges sent
                        </span>
                      )}
                      {endSummary.turn_counts &&
                        Object.keys(endSummary.turn_counts).length > 0 && (
                          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm font-medium text-slate-200">
                            {endSummary.turn_counts.tutor ?? 0} tutor turns ·{' '}
                            {endSummary.turn_counts.student ?? 0} student turns
                          </span>
                        )}
                    </div>
                  </div>

                  <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      First recommendations
                    </p>
                    {endSummaryRecommendationsToShow.length > 0 ? (
                      <ul className="mt-4 space-y-3 text-sm leading-6 text-slate-200">
                        {endSummaryRecommendationsToShow.map((recommendation, index) => (
                          <li key={`${recommendation}-${index}`} className="flex gap-3">
                            <span className="mt-1 text-violet-300">•</span>
                            <span>{recommendation}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-4 text-sm leading-6 text-slate-400">
                        No immediate follow-up recommendations were generated for this session.
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    data-testid="view-analytics-button"
                    type="button"
                    onClick={() =>
                      handleEndedSessionNavigation(`/analytics/${sessionId}`)
                    }
                    className="inline-flex items-center justify-center rounded-2xl bg-violet-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-violet-500"
                  >
                    View Full Analytics
                  </button>
                  <button
                    type="button"
                    onClick={() => handleEndedSessionNavigation('/')}
                    className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/5 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
                  >
                    Back to Dashboard
                  </button>
                </div>
              </div>
            )}

            {!endSummaryLoading && !endSummary && endSummaryFailed && (
              <div className="space-y-6 pt-8">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <p className="text-lg font-medium text-white">
                    Session ended. Full analytics are still finalizing.
                  </p>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                    The session report wasn&apos;t available yet, but the detail page will fetch it independently as soon as persistence finishes.
                  </p>
                </div>
                <div>
                  <button
                    data-testid="view-analytics-button"
                    type="button"
                    onClick={() =>
                      handleEndedSessionNavigation(`/analytics/${sessionId}`)
                    }
                    className="inline-flex items-center justify-center rounded-2xl bg-violet-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-violet-500"
                  >
                    View Full Analytics
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
