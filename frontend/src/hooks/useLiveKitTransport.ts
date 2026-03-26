'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ConnectionState,
  DataPacket_Kind,
  RemoteAudioTrack,
  RemoteVideoTrack,
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

  // Stable ref for data packet handler so room listeners always call the latest version
  const onDataPacketRef = useRef(onDataPacket)
  onDataPacketRef.current = onDataPacket

  // Keep the latest publish callback without letting the initial room
  // connection effect restart whenever the local MediaStream arrives or
  // changes. Otherwise the in-flight LiveKit join gets torn down, which shows
  // up as a user-initiated disconnect / aborted connection attempt.
  const publishLocalTracksRef = useRef<((room: Room) => Promise<void>) | null>(null)
  const fetchJoinConfigRef = useRef<(() => Promise<{
    url: string
    token: string
    room_name: string
    identity: string
  }>) | null>(null)
  const applyRoomStateRef = useRef<((room: Room) => void) | null>(null)
  const syncRemoteParticipantsRef = useRef<(() => void) | null>(null)
  const resetRemoteStateRef = useRef<(() => void) | null>(null)
  const closeConnectionRef = useRef<((reason: string) => void) | null>(null)
  const logRef = useRef<((message: string) => void) | null>(null)

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
        videoTrack: participant.videoTrack,
        audioTrack: participant.audioTrack,
      })
    })
    return snapshot
  }, [])

  const syncRemoteParticipants = useCallback(() => {
    const snapshot = buildParticipantsSnapshot()
    setRemoteParticipants(snapshot)

    const firstRemoteParticipant = snapshot.values().next().value ?? null
    const nextRemoteStream = firstRemoteParticipant?.stream ?? null
    log(
      `remote snapshot participants=${snapshot.size} primary=${firstRemoteParticipant?.identity ?? 'none'} ` +
        `tracks=${nextRemoteStream?.getTracks().length ?? 0} ` +
        `audio=${nextRemoteStream?.getAudioTracks().length ?? 0} ` +
        `video=${nextRemoteStream?.getVideoTracks().length ?? 0}`
    )
    remoteStreamRef.current = nextRemoteStream
    setRemoteStream(nextRemoteStream)
    setRemoteTrackCount(nextRemoteStream?.getTracks().length ?? 0)
  }, [buildParticipantsSnapshot, log])

  syncRemoteParticipantsRef.current = syncRemoteParticipants

  const resetRemoteState = useCallback(() => {
    remoteStreamRef.current = null
    setRemoteStream(null)
    setRemoteTrackCount(0)
    remoteParticipantsRef.current.clear()
    setRemoteParticipants(new Map())
  }, [])

  resetRemoteStateRef.current = resetRemoteState

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

  applyRoomStateRef.current = applyRoomState

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

  closeConnectionRef.current = closeConnection

  const publishLocalTracks = useCallback(async (room: Room) => {
    if (!localStream) {
      log('publish skipped: no local stream')
      return
    }

    const lkConfig = buildLiveKitConfig()
    for (const track of localStream.getTracks()) {
      if (
        publishedTrackIdsRef.current.has(track.id)
        || publishingTrackIdsRef.current.has(track.id)
      ) {
        log(
          `publish skipped for local ${track.kind} track id=${track.id} ` +
            `(already ${publishedTrackIdsRef.current.has(track.id) ? 'published' : 'publishing'})`
        )
        continue
      }

      const settings = track.getSettings?.() ?? {}
      log(
        `attempting to publish local ${track.kind} track id=${track.id} ` +
          `enabled=${track.enabled} muted=${'muted' in track ? String((track as MediaStreamTrack & { muted?: boolean }).muted) : 'n/a'} ` +
          `readyState=${track.readyState}` +
          (track.kind === 'audio'
            ? ` label=${track.label || 'unknown'} sampleRate=${settings.sampleRate ?? '?'} channelCount=${settings.channelCount ?? '?'} deviceId=${settings.deviceId ? 'present' : 'missing'}`
            : ` width=${settings.width ?? '?'} height=${settings.height ?? '?'} frameRate=${settings.frameRate ?? '?'}`)
      )

      const publishOpts =
        track.kind === 'video'
          ? lkConfig.videoPublishOptions
          : lkConfig.audioPublishOptions

      publishingTrackIdsRef.current.add(track.id)
      try {
        await room.localParticipant.publishTrack(track, publishOpts)
        publishedTrackIdsRef.current.add(track.id)
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

  publishLocalTracksRef.current = publishLocalTracks

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

  fetchJoinConfigRef.current = fetchJoinConfig
  logRef.current = log

  useEffect(() => {
    if (!enabled) {
      setError(null)
      logRef.current?.('transport disabled -> closing active room if present')
      closeConnectionRef.current?.('transport disabled')
      return
    }

    if (!role || !sessionId || !sessionToken) {
      logRef.current?.(
        `transport waiting for inputs role=${role ?? 'null'} session=${sessionId ? 'yes' : 'no'} token=${sessionToken ? 'yes' : 'no'}`
      )
      return
    }

    let cancelled = false
    const audioTrackCount = localStream?.getAudioTracks().length ?? 0
    const videoTrackCount = localStream?.getVideoTracks().length ?? 0

    logRef.current?.(
      `connect effect start role=${role} audioTracks=${audioTrackCount} videoTracks=${videoTrackCount}`
    )

    const connect = async () => {
      try {
        setError(null)
        setCallStatus('connecting')

        logRef.current?.('requesting LiveKit join config')

        const join = await fetchJoinConfigRef.current?.()
        if (!join) {
          throw new Error('Failed to create LiveKit join token')
        }
        logRef.current?.(
          `join config received room=${join.room_name} identity=${join.identity} url=${join.url || LIVEKIT_URL || 'missing'}`
        )
        if (cancelled) return

        const lkConfig = buildLiveKitConfig()
        const room = new Room(lkConfig.roomOptions)
        roomRef.current = room

        room.on(RoomEvent.Connected, () => {
          logRef.current?.('connected')
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.Reconnected, () => {
          logRef.current?.('reconnected')
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.Disconnected, () => {
          logRef.current?.('disconnected')
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.ParticipantConnected, (participant) => {
          logRef.current?.(`participant connected: ${participant.identity}`)
          if (participant.identity.startsWith('worker:')) {
            return
          }
          remoteParticipantDisconnectedRef.current = false
          setCallStatus('connecting')
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.ParticipantDisconnected, (participant) => {
          logRef.current?.(`participant disconnected: ${participant.identity}`)
          // Worker identities drive analytics, not UI; ignore them entirely.
          if (!participant.identity.startsWith('worker:')) {
            remoteParticipantsRef.current.delete(participant.identity)
            syncRemoteParticipantsRef.current?.()
            if (remoteParticipantsRef.current.size === 0) {
              remoteParticipantDisconnectedRef.current = true
              resetRemoteStateRef.current?.()
              setCallStatus('reconnecting')
            }
          }
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
          // Exclude analytics-worker participants from the UI participant map.
          if (participant.identity.startsWith('worker:')) {
            logRef.current?.(`skipping worker track (${track.kind}) from ${participant.identity}`)
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
              videoTrack: undefined,
              audioTrack: undefined,
            }
            remoteParticipantsRef.current.set(identity, remoteParticipant)
          }
          if (track.kind === Track.Kind.Video && track instanceof RemoteVideoTrack) {
            remoteParticipant.videoTrack = track
          }
          if (track.kind === Track.Kind.Audio && track instanceof RemoteAudioTrack) {
            remoteParticipant.audioTrack = track
          }
          if (!remoteParticipant.stream.getTracks().find((t) => t.id === track.mediaStreamTrack.id)) {
            remoteParticipant.stream.addTrack(track.mediaStreamTrack)
          }

          syncRemoteParticipantsRef.current?.()
          setCallStatus('connected')
          logRef.current?.(`subscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.TrackUnsubscribed, (track, _publication, participant) => {
          if (!participant.identity.startsWith('worker:')) {
            const remoteParticipant = remoteParticipantsRef.current.get(participant.identity)
            if (remoteParticipant) {
              if (track.kind === Track.Kind.Video) {
                remoteParticipant.videoTrack = undefined
              }
              if (track.kind === Track.Kind.Audio) {
                remoteParticipant.audioTrack = undefined
              }
              remoteParticipant.stream.removeTrack(track.mediaStreamTrack)
              if (remoteParticipant.stream.getTracks().length === 0) {
                remoteParticipantsRef.current.delete(participant.identity)
              }
            }
            syncRemoteParticipantsRef.current?.()
          }
          if (remoteParticipantsRef.current.size === 0 && remoteParticipantDisconnectedRef.current) {
            setCallStatus('reconnecting')
          }
          logRef.current?.(`unsubscribed remote ${track.kind} from ${participant.identity}`)
        })
        room.on(RoomEvent.ConnectionStateChanged, (state) => {
          logRef.current?.(`connection state=${state}`)
          applyRoomStateRef.current?.(room)
        })
        room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
          if (onDataPacketRef.current && topic) {
            onDataPacketRef.current(topic, payload)
          }
        })

        const url = join.url || LIVEKIT_URL
        if (!url) {
          throw new Error('Missing LiveKit URL')
        }

        // Best-effort prewarm: primes DNS/TLS/edge routing before full connect.
        logRef.current?.('preparing LiveKit connection')
        await room.prepareConnection(url, join.token)
        logRef.current?.('connecting to LiveKit room')
        await room.connect(url, join.token)
        if (cancelled) {
          await room.disconnect()
          return
        }
        logRef.current?.('LiveKit room.connect resolved')
        applyRoomStateRef.current?.(room)
        await publishLocalTracksRef.current?.(room)
      } catch (connectionError) {
        const message =
          connectionError instanceof Error
            ? connectionError.message
            : 'Failed to connect to LiveKit room'
        setError(message)
        setCallStatus('disabled')
        logRef.current?.(`connection failed: ${message}`)
      }
    }

    void connect()

    return () => {
      cancelled = true
      logRef.current?.('connect effect cleanup -> disconnecting room')
      closeConnectionRef.current?.('effect cleanup')
    }
  }, [
    enabled,
    role,
    sessionId,
    sessionToken,
  ])

  useEffect(() => {
    const room = roomRef.current
    if (!enabled || !room || !localStream || room.state !== ConnectionState.Connected) {
      return
    }

    logRef.current?.(
      `local stream update -> publish attempt audio=${localStream.getAudioTracks().length} video=${localStream.getVideoTracks().length}`
    )
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

  const setMicEnabled = useCallback(
    async (enabled: boolean) => {
      const room = roomRef.current
      if (!room || room.state !== ConnectionState.Connected) return
      try {
        await room.localParticipant.setMicrophoneEnabled(enabled)
        log(enabled ? 'mic unmuted via LiveKit' : 'mic muted via LiveKit')
      } catch (e) {
        log(`setMicrophoneEnabled(${enabled}) failed: ${e instanceof Error ? e.message : 'unknown'}`)
      }
    },
    [log]
  )

  const setCameraEnabled = useCallback(
    async (enabled: boolean) => {
      const room = roomRef.current
      if (!room || room.state !== ConnectionState.Connected) return
      try {
        await room.localParticipant.setCameraEnabled(enabled)
        log(enabled ? 'camera unmuted via LiveKit' : 'camera muted via LiveKit')
      } catch (e) {
        log(`setCameraEnabled(${enabled}) failed: ${e instanceof Error ? e.message : 'unknown'}`)
      }
    },
    [log]
  )

  const replacePublishedTrack = useCallback(
    async (kind: 'audio' | 'video', previousTrack: MediaStreamTrack | null, nextTrack: MediaStreamTrack) => {
      const room = roomRef.current
      if (!room || room.state !== ConnectionState.Connected) {
        log(`replace ${kind} skipped: room not connected`)
        return
      }

      try {
        if (previousTrack) {
          await room.localParticipant.unpublishTrack(previousTrack, false)
          publishedTrackIdsRef.current.delete(previousTrack.id)
          publishingTrackIdsRef.current.delete(previousTrack.id)
          log(`unpublished local ${kind} track id=${previousTrack.id}`)
        }

        const lkConfig = buildLiveKitConfig()
        const publishOpts =
          kind === 'video'
            ? lkConfig.videoPublishOptions
            : lkConfig.audioPublishOptions

        await room.localParticipant.publishTrack(nextTrack, publishOpts)
        publishedTrackIdsRef.current.add(nextTrack.id)
        log(`published replacement local ${kind} track id=${nextTrack.id}`)
      } catch (e) {
        log(
          `replace ${kind} failed: ${e instanceof Error ? e.message : 'unknown'}`
        )
      }
    },
    [log]
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
    /** Mute/unmute mic on the LiveKit published track. */
    setMicEnabled,
    /** Enable/disable camera on the LiveKit published track. */
    setCameraEnabled,
    replacePublishedTrack,
  }
}
