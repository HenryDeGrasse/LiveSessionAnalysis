'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ConnectionState, Room, RoomEvent, Track } from 'livekit-client'
import {
  API_URL,
  LIVEKIT_ADAPTIVE_STREAM,
  LIVEKIT_DYNACAST,
  LIVEKIT_URL,
} from '@/lib/constants'
import type { WebRTCSignalData } from '@/lib/types'

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
  onDebugEvent?: (message: string) => void
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
  onDebugEvent,
}: UseLiveKitTransportOptions) {
  const roomRef = useRef<Room | null>(null)
  const publishedTrackIdsRef = useRef<Set<string>>(new Set())
  const publishingTrackIdsRef = useRef<Set<string>>(new Set())
  const remoteStreamRef = useRef<MediaStream | null>(null)
  const remoteParticipantDisconnectedRef = useRef(false)

  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
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

  const resetRemoteState = useCallback(() => {
    remoteStreamRef.current = null
    setRemoteStream(null)
    setRemoteTrackCount(0)
  }, [])

  const syncRemoteTrackCount = useCallback(() => {
    setRemoteTrackCount(remoteStreamRef.current?.getTracks().length ?? 0)
  }, [])

  const ensureRemoteStream = useCallback(() => {
    if (!remoteStreamRef.current) {
      remoteStreamRef.current = new MediaStream()
      setRemoteStream(remoteStreamRef.current)
    }
    return remoteStreamRef.current
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
    const hasRemoteParticipant = room.remoteParticipants.size > 0 || hasRemoteTracks

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

    for (const track of localStream.getTracks()) {
      if (
        publishedTrackIdsRef.current.has(track.id)
        || publishingTrackIdsRef.current.has(track.id)
      ) {
        continue
      }

      publishingTrackIdsRef.current.add(track.id)
      try {
        await room.localParticipant.publishTrack(track)
        publishedTrackIdsRef.current.add(track.id)
        log(`published local ${track.kind} track`)
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
    const response = await fetch(
      `${API_URL}/api/sessions/${sessionId}/livekit-token?token=${encodeURIComponent(sessionToken)}`,
      { method: 'POST' }
    )

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(
        payload?.detail || 'Failed to create LiveKit join token'
      )
    }

    return (await response.json()) as {
      url: string
      token: string
      room_name: string
      identity: string
    }
  }, [sessionId, sessionToken])

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

        const room = new Room({
          adaptiveStream: LIVEKIT_ADAPTIVE_STREAM,
          dynacast: LIVEKIT_DYNACAST,
        })
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
          remoteParticipantDisconnectedRef.current = false
          setCallStatus('connecting')
          applyRoomState(room)
        })
        room.on(RoomEvent.ParticipantDisconnected, (participant) => {
          log(`participant disconnected: ${participant.identity}`)
          remoteParticipantDisconnectedRef.current = true
          resetRemoteState()
          setCallStatus('reconnecting')
          applyRoomState(room)
        })
        room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
          const stream = ensureRemoteStream()
          remoteParticipantDisconnectedRef.current = false
          if (!stream.getTracks().find((candidate) => candidate.id === track.mediaStreamTrack.id)) {
            stream.addTrack(track.mediaStreamTrack)
          }
          syncRemoteTrackCount()
          setCallStatus('connected')
          log(`subscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.TrackUnsubscribed, (track, _publication, participant) => {
          if (remoteStreamRef.current) {
            remoteStreamRef.current.removeTrack(track.mediaStreamTrack)
          }
          syncRemoteTrackCount()
          if (remoteParticipantDisconnectedRef.current) {
            setCallStatus('reconnecting')
          }
          log(`unsubscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.ConnectionStateChanged, (state) => {
          log(`connection state=${state}`)
          applyRoomState(room)
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
    ensureRemoteStream,
    log,
    publishLocalTracks,
    resetRemoteState,
    syncRemoteTrackCount,
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
