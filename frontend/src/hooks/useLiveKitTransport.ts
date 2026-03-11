'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ConnectionState,
  DataPacket_Kind,
  Room,
  RoomEvent,
  Track,
} from 'livekit-client'
import { LIVEKIT_URL } from '@/lib/constants'
import { apiFetch } from '@/lib/api-client'
import { buildLiveKitConfig } from '@/lib/call/livekit-config'
import type { RemoteParticipant, WebRTCSignalData } from '@/lib/types'

type SessionRole = 'tutor' | 'student'

type CallStatus =
  | 'disabled'
  | 'waiting_for_participant'
  | 'connecting'
  | 'connected'
  | 'reconnecting'

interface UseLiveKitTransportOptions {
  enabled: boolean
  role: SessionRole | null
  localStream: MediaStream | null
  sessionId: string
  sessionToken: string
  /** Optional user-level JWT (from NextAuth session) for authenticated API calls. */
  accessToken?: string
  debug?: boolean
  onDebugEvent?: (message: string) => void
  onDataPacket?: (topic: string, payload: Uint8Array) => void
}

function mapConnectionStateToPeerState(
  state: ConnectionState
): RTCPeerConnectionState {
  switch (state) {
    case ConnectionState.Connected:
      return 'connected'
    case ConnectionState.Connecting:
      return 'connecting'
    case ConnectionState.Reconnecting:
    case ConnectionState.SignalReconnecting:
      return 'disconnected'
    case ConnectionState.Disconnected:
    default:
      return 'closed'
  }
}

export function useLiveKitTransport({
  enabled,
  role,
  localStream,
  sessionId,
  sessionToken,
  accessToken,
  debug,
  onDebugEvent,
  onDataPacket,
}: UseLiveKitTransportOptions) {
  const roomRef = useRef<Room | null>(null)
  const publishedTrackIdsRef = useRef<Set<string>>(new Set())
  const publishingTrackIdsRef = useRef<Set<string>>(new Set())
  const remoteStreamRef = useRef<MediaStream | null>(null)
  /** Per-participant streams, keyed by LiveKit identity (excludes worker:* identities). */
  const remoteParticipantsRef = useRef<Map<string, RemoteParticipant>>(new Map())
  const remoteParticipantDisconnectedRef = useRef(false)

  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [remoteParticipants, setRemoteParticipants] = useState<Map<string, RemoteParticipant>>(new Map())
  const [callStatus, setCallStatus] = useState<CallStatus>(
    enabled ? 'waiting_for_participant' : 'disabled'
  )
  const [connectionState, setConnectionState] = useState<RTCPeerConnectionState>('new')
  const [iceConnectionState, setIceConnectionState] =
    useState<RTCIceConnectionState>('new')
  const [iceGatheringState, setIceGatheringState] =
    useState<RTCIceGatheringState>('new')
  const [signalingState, setSignalingState] = useState<RTCSignalingState>('stable')
  const [remoteTrackCount, setRemoteTrackCount] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const log = useCallback(
    (message: string) => {
      onDebugEvent?.(`livekit: ${message}`)
    },
    [onDebugEvent]
  )

  /** Build a React-state-safe snapshot of the current per-participant map. */
  const buildParticipantsSnapshot = useCallback((): Map<string, RemoteParticipant> => {
    const snapshot = new Map<string, RemoteParticipant>()
    Array.from(remoteParticipantsRef.current.entries()).forEach(([identity, participant]) => {
      snapshot.set(identity, {
        identity,
        stream: participant.stream,
        hasVideo: participant.stream
          .getVideoTracks()
          .some((t: MediaStreamTrack) => t.readyState === 'live'),
        hasAudio: participant.stream
          .getAudioTracks()
          .some((t: MediaStreamTrack) => t.readyState === 'live'),
      })
    })
    return snapshot
  }, [])

  const syncRemoteParticipants = useCallback(() => {
    const snapshot = buildParticipantsSnapshot()
    setRemoteParticipants(snapshot)

    const firstRemoteParticipant = snapshot.values().next().value ?? null
    const nextRemoteStream = firstRemoteParticipant?.stream ?? null
    remoteStreamRef.current = nextRemoteStream
    setRemoteStream(nextRemoteStream)
    setRemoteTrackCount(nextRemoteStream?.getTracks().length ?? 0)
  }, [buildParticipantsSnapshot])

  const resetRemoteState = useCallback(() => {
    remoteStreamRef.current = null
    setRemoteStream(null)
    setRemoteTrackCount(0)
    remoteParticipantsRef.current.clear()
    setRemoteParticipants(new Map())
  }, [])

  const applyRoomState = useCallback((room: Room) => {
    setConnectionState(mapConnectionStateToPeerState(room.state))
    setIceConnectionState(
      room.state === ConnectionState.Connected ? 'connected' : room.state === ConnectionState.Connecting ? 'checking' : room.state === ConnectionState.Reconnecting || room.state === ConnectionState.SignalReconnecting ? 'disconnected' : 'closed'
    )
    setIceGatheringState(room.state === ConnectionState.Connecting ? 'gathering' : 'complete')
    setSignalingState(room.state === ConnectionState.Disconnected ? 'closed' : 'stable')

    const hasRemoteTracks = Boolean(
      remoteStreamRef.current?.getTracks().some((track) => track.readyState === 'live')
    )
    const hasRemoteParticipant = remoteParticipantsRef.current.size > 0 || hasRemoteTracks

    if (room.state === ConnectionState.Connected) {
      if (remoteParticipantDisconnectedRef.current) {
        setCallStatus('reconnecting')
      } else {
        setCallStatus(hasRemoteParticipant ? 'connected' : 'waiting_for_participant')
      }
    } else if (room.state === ConnectionState.Connecting) {
      setCallStatus('connecting')
    } else if (
      room.state === ConnectionState.Reconnecting ||
      room.state === ConnectionState.SignalReconnecting
    ) {
      setCallStatus('reconnecting')
    } else {
      setCallStatus(enabled ? 'waiting_for_participant' : 'disabled')
    }
  }, [enabled])

  const closeConnection = useCallback(
    (reason: string) => {
      const room = roomRef.current
      if (room) {
        log(`disconnecting room (${reason})`)
        void room.disconnect()
      }
      roomRef.current = null
      publishedTrackIdsRef.current.clear()
      publishingTrackIdsRef.current.clear()
      remoteParticipantDisconnectedRef.current = false
      resetRemoteState()
      setConnectionState('closed')
      setIceConnectionState('closed')
      setIceGatheringState('complete')
      setSignalingState('closed')
      setCallStatus(enabled ? 'waiting_for_participant' : 'disabled')
    },
    [enabled, log, resetRemoteState]
  )

  const publishLocalTracks = useCallback(async (room: Room) => {
    if (!localStream) return

    const lkConfig = buildLiveKitConfig()
    for (const track of localStream.getTracks()) {
      if (
        publishedTrackIdsRef.current.has(track.id)
        || publishingTrackIdsRef.current.has(track.id)
      ) {
        continue
      }

      const publishOpts =
        track.kind === 'video'
          ? lkConfig.videoPublishOptions
          : lkConfig.audioPublishOptions

      publishingTrackIdsRef.current.add(track.id)
      try {
        await room.localParticipant.publishTrack(track, publishOpts)
        publishedTrackIdsRef.current.add(track.id)
        const settings = track.getSettings?.() ?? {}
        log(
          `published local ${track.kind} track` +
            (track.kind === 'video'
              ? ` (${settings.width ?? '?'}x${settings.height ?? '?'}@${settings.frameRate ?? '?'}fps, ` +
                `encoding=${publishOpts.videoEncoding?.maxBitrate ?? 'default'}bps)`
              : '')
        )
      } catch (publishError) {
        log(
          `failed to publish local ${track.kind} track: ${publishError instanceof Error ? publishError.message : 'unknown error'}`
        )
        throw publishError
      } finally {
        publishingTrackIdsRef.current.delete(track.id)
      }
    }
  }, [localStream, log])

  const fetchJoinConfig = useCallback(async () => {
    const response = await apiFetch(
      `/api/sessions/${sessionId}/livekit-token?token=${encodeURIComponent(sessionToken)}${debug ? '&debug=1' : ''}`,
      { method: 'POST', accessToken }
    )

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(
        (payload as { detail?: string })?.detail || 'Failed to create LiveKit join token'
      )
    }

    return (await response.json()) as {
      url: string
      token: string
      room_name: string
      identity: string
    }
  }, [sessionId, sessionToken, accessToken, debug])

  useEffect(() => {
    if (!enabled) {
      setError(null)
      closeConnection('transport disabled')
      return
    }

    if (!role || !localStream || !sessionId || !sessionToken) {
      return
    }

    let cancelled = false

    const connect = async () => {
      try {
        setError(null)
        setCallStatus('connecting')

        const join = await fetchJoinConfig()
        if (cancelled) return

        const lkConfig = buildLiveKitConfig()
        const room = new Room(lkConfig.roomOptions)
        roomRef.current = room

        room.on(RoomEvent.Connected, () => {
          log('connected')
          applyRoomState(room)
        })
        room.on(RoomEvent.Reconnected, () => {
          log('reconnected')
          applyRoomState(room)
        })
        room.on(RoomEvent.Disconnected, () => {
          log('disconnected')
          applyRoomState(room)
        })
        room.on(RoomEvent.ParticipantConnected, (participant) => {
          log(`participant connected: ${participant.identity}`)
          if (participant.identity.startsWith('worker:')) {
            return
          }
          remoteParticipantDisconnectedRef.current = false
          setCallStatus('connecting')
          applyRoomState(room)
        })
        room.on(RoomEvent.ParticipantDisconnected, (participant) => {
          log(`participant disconnected: ${participant.identity}`)
          // Worker identities drive analytics, not UI; ignore them entirely.
          if (!participant.identity.startsWith('worker:')) {
            remoteParticipantsRef.current.delete(participant.identity)
            syncRemoteParticipants()
            if (remoteParticipantsRef.current.size === 0) {
              remoteParticipantDisconnectedRef.current = true
              resetRemoteState()
              setCallStatus('reconnecting')
            }
          }
          applyRoomState(room)
        })
        room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
          // Exclude analytics-worker participants from the UI participant map.
          if (participant.identity.startsWith('worker:')) {
            log(`skipping worker track (${track.kind}) from ${participant.identity}`)
            return
          }

          remoteParticipantDisconnectedRef.current = false
          const identity = participant.identity

          // Per-participant stream: one MediaStream per remote identity.
          let remoteParticipant = remoteParticipantsRef.current.get(identity)
          if (!remoteParticipant) {
            remoteParticipant = {
              identity,
              stream: new MediaStream(),
              hasVideo: false,
              hasAudio: false,
            }
            remoteParticipantsRef.current.set(identity, remoteParticipant)
          }
          if (!remoteParticipant.stream.getTracks().find((t) => t.id === track.mediaStreamTrack.id)) {
            remoteParticipant.stream.addTrack(track.mediaStreamTrack)
          }

          syncRemoteParticipants()
          setCallStatus('connected')
          log(`subscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.TrackUnsubscribed, (track, _publication, participant) => {
          if (!participant.identity.startsWith('worker:')) {
            const remoteParticipant = remoteParticipantsRef.current.get(participant.identity)
            if (remoteParticipant) {
              remoteParticipant.stream.removeTrack(track.mediaStreamTrack)
              if (remoteParticipant.stream.getTracks().length === 0) {
                remoteParticipantsRef.current.delete(participant.identity)
              }
            }
            syncRemoteParticipants()
          }
          if (remoteParticipantsRef.current.size === 0 && remoteParticipantDisconnectedRef.current) {
            setCallStatus('reconnecting')
          }
          log(`unsubscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.ConnectionStateChanged, (state) => {
          log(`connection state=${state}`)
          applyRoomState(room)
        })
        room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
          if (onDataPacket && topic) {
            onDataPacket(topic, payload)
          }
        })

        const url = join.url || LIVEKIT_URL
        if (!url) {
          throw new Error('Missing LiveKit URL')
        }

        await room.connect(url, join.token)
        if (cancelled) {
          await room.disconnect()
          return
        }
        applyRoomState(room)
        await publishLocalTracks(room)
      } catch (connectionError) {
        const message =
          connectionError instanceof Error
            ? connectionError.message
            : 'Failed to connect to LiveKit room'
        setError(message)
        setCallStatus('disabled')
        log(`connection failed: ${message}`)
      }
    }

    void connect()

    return () => {
      cancelled = true
      closeConnection('effect cleanup')
    }
  }, [
    enabled,
    role,
    localStream,
    sessionId,
    sessionToken,
    fetchJoinConfig,
    applyRoomState,
    closeConnection,
    log,
    publishLocalTracks,
    resetRemoteState,
    syncRemoteParticipants,
  ])

  useEffect(() => {
    const room = roomRef.current
    if (!enabled || !room || !localStream || room.state !== ConnectionState.Connected) {
      return
    }

    void publishLocalTracks(room)
  }, [enabled, localStream, publishLocalTracks])

  const handleSignal = useCallback(async (_signal: WebRTCSignalData) => {
    // LiveKit does not use the custom signaling channel for media transport.
  }, [])

  const handleParticipantReady = useCallback(async () => {
    remoteParticipantDisconnectedRef.current = false
    const room = roomRef.current
    if (room) {
      applyRoomState(room)
    }
  }, [applyRoomState])

  const handleParticipantDisconnected = useCallback(() => {
    remoteParticipantDisconnectedRef.current = true
    resetRemoteState()
    setCallStatus((current) => (current === 'disabled' ? current : 'reconnecting'))
    log('participant disconnected (app presence)')
  }, [log, resetRemoteState])

  const handleParticipantReconnected = useCallback(async () => {
    remoteParticipantDisconnectedRef.current = false
    const room = roomRef.current
    if (room) {
      setCallStatus('connecting')
      applyRoomState(room)
    }
    log('participant reconnected (app presence)')
  }, [applyRoomState, log])

  const hasRemoteVideo = useMemo(
    () =>
      Boolean(
        remoteStream?.getVideoTracks().some((track) => track.readyState === 'live')
      ),
    [remoteStream, remoteTrackCount]
  )
  const hasRemoteAudio = useMemo(
    () =>
      Boolean(
        remoteStream?.getAudioTracks().some((track) => track.readyState === 'live')
      ),
    [remoteStream, remoteTrackCount]
  )

  return {
    remoteStream,
    remoteTrackCount,
    hasRemoteVideo,
    hasRemoteAudio,
    /** Map of visible remote participant identities to their per-participant data. */
    remoteParticipants,
    callStatus,
    connectionState,
    iceConnectionState,
    iceGatheringState,
    signalingState,
    error,
    handleSignal,
    handleParticipantReady,
    handleParticipantDisconnected,
    handleParticipantReconnected,
    closeConnection,
  }
}
