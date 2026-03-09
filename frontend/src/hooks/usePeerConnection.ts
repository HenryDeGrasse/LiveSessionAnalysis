'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { WEBRTC_ICE_SERVERS } from '@/lib/constants'
import type { WebRTCSignalData } from '@/lib/types'

type SessionRole = 'tutor' | 'student'
type OutboundSignal = {
  signal_type: 'offer' | 'answer' | 'ice_candidate'
  payload: Record<string, unknown>
}

type CallStatus =
  | 'disabled'
  | 'waiting_for_participant'
  | 'connecting'
  | 'connected'
  | 'reconnecting'

interface UsePeerConnectionOptions {
  enabled: boolean
  role: SessionRole | null
  localStream: MediaStream | null
  sendSignal: (signal: OutboundSignal) => void
  onDebugEvent?: (message: string) => void
}

function serializeDescription(description: RTCSessionDescriptionInit | RTCSessionDescription) {
  return {
    type: description.type,
    sdp: description.sdp ?? '',
  }
}

export function usePeerConnection({
  enabled,
  role,
  localStream,
  sendSignal,
  onDebugEvent,
}: UsePeerConnectionOptions) {
  const pcRef = useRef<RTCPeerConnection | null>(null)
  const remoteStreamRef = useRef<MediaStream | null>(null)
  const participantReadyRef = useRef(false)
  const makingOfferRef = useRef(false)
  const queuedSignalsRef = useRef<WebRTCSignalData[]>([])
  const pendingIceCandidatesRef = useRef<RTCIceCandidateInit[]>([])

  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [callStatus, setCallStatus] = useState<CallStatus>(
    enabled ? 'waiting_for_participant' : 'disabled'
  )
  const [connectionState, setConnectionState] = useState<RTCPeerConnectionState>('new')
  const [iceConnectionState, setIceConnectionState] = useState<RTCIceConnectionState>('new')
  const [iceGatheringState, setIceGatheringState] = useState<RTCIceGatheringState>('new')
  const [signalingState, setSignalingState] = useState<RTCSignalingState>('stable')
  const [error, setError] = useState<string | null>(null)
  const [remoteTrackCount, setRemoteTrackCount] = useState(0)

  const log = useCallback(
    (message: string) => {
      onDebugEvent?.(`webrtc: ${message}`)
    },
    [onDebugEvent]
  )

  const clearRemoteState = useCallback(() => {
    remoteStreamRef.current = null
    setRemoteStream(null)
    setRemoteTrackCount(0)
  }, [])

  const closeConnection = useCallback(
    (reason: string) => {
      const pc = pcRef.current
      if (pc) {
        log(`closing peer connection (${reason})`)
        pc.ontrack = null
        pc.onicecandidate = null
        pc.onconnectionstatechange = null
        pc.oniceconnectionstatechange = null
        pc.onicegatheringstatechange = null
        pc.onsignalingstatechange = null
        pc.close()
      }
      pcRef.current = null
      pendingIceCandidatesRef.current = []
      clearRemoteState()
      setConnectionState('closed')
      setIceConnectionState('closed')
      setIceGatheringState('complete')
      setSignalingState('closed')
    },
    [clearRemoteState, log]
  )

  const flushPendingIceCandidates = useCallback(async (pc: RTCPeerConnection) => {
    while (pendingIceCandidatesRef.current.length > 0) {
      const candidate = pendingIceCandidatesRef.current.shift()
      if (!candidate) continue
      try {
        await pc.addIceCandidate(candidate)
      } catch (candidateError) {
        log(
          `failed to add queued ICE candidate: ${candidateError instanceof Error ? candidateError.message : 'unknown error'}`
        )
      }
    }
  }, [log])

  const ensurePeerConnection = useCallback(() => {
    if (!enabled || !role || !localStream || typeof RTCPeerConnection === 'undefined') {
      return null
    }

    if (pcRef.current && pcRef.current.connectionState !== 'closed') {
      return pcRef.current
    }

    const pc = new RTCPeerConnection({
      iceServers: WEBRTC_ICE_SERVERS,
    })

    remoteStreamRef.current = new MediaStream()
    setRemoteStream(remoteStreamRef.current)
    setRemoteTrackCount(0)
    setConnectionState(pc.connectionState)
    setIceConnectionState(pc.iceConnectionState)
    setIceGatheringState(pc.iceGatheringState)
    setSignalingState(pc.signalingState)

    localStream.getTracks().forEach((track) => {
      pc.addTrack(track, localStream)
    })

    pc.ontrack = (event) => {
      const nextStream = event.streams[0] || remoteStreamRef.current || new MediaStream()
      if (!event.streams[0]) {
        nextStream.addTrack(event.track)
      }
      remoteStreamRef.current = nextStream
      setRemoteStream(nextStream)
      setRemoteTrackCount(nextStream.getTracks().length)
      setCallStatus('connected')
      log(`remote ${event.track.kind} track received`)
    }

    pc.onicecandidate = (event) => {
      if (!event.candidate) return
      sendSignal({
        signal_type: 'ice_candidate',
        payload: event.candidate.toJSON() as Record<string, unknown>,
      })
    }

    pc.onconnectionstatechange = () => {
      setConnectionState(pc.connectionState)
      const hasLiveRemoteTracks = Boolean(
        remoteStreamRef.current?.getTracks().some((track) => track.readyState === 'live')
      )

      if (pc.connectionState === 'connected') {
        setCallStatus('connected')
      } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
        setCallStatus(
          hasLiveRemoteTracks
            ? 'connected'
            : participantReadyRef.current
            ? 'reconnecting'
            : 'waiting_for_participant'
        )
      } else if (pc.connectionState === 'connecting') {
        setCallStatus(hasLiveRemoteTracks ? 'connected' : 'connecting')
      }
      log(`connection=${pc.connectionState}`)
    }

    pc.oniceconnectionstatechange = () => {
      setIceConnectionState(pc.iceConnectionState)
      const hasLiveRemoteTracks = Boolean(
        remoteStreamRef.current?.getTracks().some((track) => track.readyState === 'live')
      )
      if (
        pc.iceConnectionState === 'connected'
        || pc.iceConnectionState === 'completed'
      ) {
        setCallStatus('connected')
      } else if (pc.iceConnectionState === 'disconnected') {
        setCallStatus(hasLiveRemoteTracks ? 'connected' : 'reconnecting')
      }
      log(`ice_connection=${pc.iceConnectionState}`)
    }

    pc.onicegatheringstatechange = () => {
      setIceGatheringState(pc.iceGatheringState)
      log(`ice_gathering=${pc.iceGatheringState}`)
    }

    pc.onsignalingstatechange = () => {
      setSignalingState(pc.signalingState)
      log(`signaling=${pc.signalingState}`)
    }

    pcRef.current = pc
    log('peer connection created')
    return pc
  }, [enabled, localStream, log, role, sendSignal])

  const startOffer = useCallback(async (reason: string) => {
    if (!enabled || role !== 'tutor' || !participantReadyRef.current || !localStream) {
      return
    }

    const pc = ensurePeerConnection()
    if (!pc) return
    if (makingOfferRef.current) {
      log(`offer skipped (${reason}) because another offer is already in flight`)
      return
    }
    if (pc.signalingState !== 'stable') {
      log(`offer skipped (${reason}) because signaling is ${pc.signalingState}`)
      return
    }

    try {
      makingOfferRef.current = true
      setError(null)
      setCallStatus('connecting')
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      sendSignal({
        signal_type: 'offer',
        payload: serializeDescription(offer),
      })
      log(`offer sent (${reason})`)
    } catch (offerError) {
      const message = offerError instanceof Error ? offerError.message : 'Failed to create offer'
      setError(message)
      log(`offer failed: ${message}`)
    } finally {
      makingOfferRef.current = false
    }
  }, [enabled, ensurePeerConnection, localStream, log, role, sendSignal])

  const handleSignal = useCallback(async (signal: WebRTCSignalData) => {
    if (!enabled) return

    if (!role || !localStream) {
      queuedSignalsRef.current.push(signal)
      log(`queued ${signal.signal_type} until local media is ready`)
      return
    }

    let pc = ensurePeerConnection()
    if (!pc) {
      queuedSignalsRef.current.push(signal)
      return
    }

    try {
      setError(null)

      if (signal.signal_type === 'offer') {
        if (role !== 'student') {
          log('ignoring unexpected offer on tutor side')
          return
        }

        if (pc.signalingState !== 'stable') {
          closeConnection('resetting before handling new offer')
          pc = ensurePeerConnection()
          if (!pc) return
        }

        await pc.setRemoteDescription(
          signal.payload as unknown as RTCSessionDescriptionInit
        )
        await flushPendingIceCandidates(pc)
        const answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        sendSignal({
          signal_type: 'answer',
          payload: serializeDescription(answer),
        })
        setCallStatus('connecting')
        log('answer sent')
        return
      }

      if (signal.signal_type === 'answer') {
        if (role !== 'tutor') {
          log('ignoring unexpected answer on student side')
          return
        }
        await pc.setRemoteDescription(
          signal.payload as unknown as RTCSessionDescriptionInit
        )
        await flushPendingIceCandidates(pc)
        setCallStatus('connecting')
        log('answer applied')
        return
      }

      const candidate = signal.payload as RTCIceCandidateInit
      if (!pc.remoteDescription) {
        pendingIceCandidatesRef.current.push(candidate)
        log('queued ICE candidate until remote description is ready')
        return
      }
      await pc.addIceCandidate(candidate)
    } catch (signalError) {
      const message = signalError instanceof Error ? signalError.message : 'Failed to handle WebRTC signal'
      setError(message)
      log(`signal handling failed: ${message}`)
    }
  }, [closeConnection, enabled, ensurePeerConnection, flushPendingIceCandidates, localStream, log, role, sendSignal])

  const processQueuedSignals = useCallback(async () => {
    if (!enabled || !role || !localStream || queuedSignalsRef.current.length === 0) {
      return
    }

    const queued = [...queuedSignalsRef.current]
    queuedSignalsRef.current = []
    for (const signal of queued) {
      await handleSignal(signal)
    }
  }, [enabled, handleSignal, localStream, role])

  const handleParticipantReady = useCallback(async () => {
    participantReadyRef.current = true
    setCallStatus((current) => (current === 'connected' ? current : 'connecting'))
    log('participant ready')
    if (role === 'tutor') {
      await startOffer('participant_ready')
    }
  }, [log, role, startOffer])

  const handleParticipantDisconnected = useCallback(() => {
    participantReadyRef.current = false
    closeConnection('participant disconnected')
    setCallStatus('reconnecting')
    log('participant disconnected')
  }, [closeConnection, log])

  const handleParticipantReconnected = useCallback(async () => {
    participantReadyRef.current = true
    closeConnection('participant reconnected')
    setCallStatus('connecting')
    log('participant reconnected')
    if (role === 'tutor') {
      await startOffer('participant_reconnected')
    }
  }, [closeConnection, log, role, startOffer])

  useEffect(() => {
    if (!enabled) {
      participantReadyRef.current = false
      queuedSignalsRef.current = []
      closeConnection('webrtc disabled')
      setCallStatus('disabled')
      setError(null)
      return
    }

    setCallStatus((current) =>
      current === 'disabled' ? 'waiting_for_participant' : current
    )
  }, [closeConnection, enabled])

  useEffect(() => {
    if (!enabled || !localStream || !role) return
    void processQueuedSignals()
    if (participantReadyRef.current && role === 'tutor') {
      void startOffer('local stream ready')
    }
  }, [enabled, localStream, processQueuedSignals, role, startOffer])

  useEffect(() => {
    return () => {
      closeConnection('hook cleanup')
    }
  }, [closeConnection])

  const hasRemoteVideo = useMemo(
    () => Boolean(remoteStream?.getVideoTracks().some((track) => track.readyState === 'live')),
    [remoteStream, remoteTrackCount]
  )
  const hasRemoteAudio = useMemo(
    () => Boolean(remoteStream?.getAudioTracks().some((track) => track.readyState === 'live')),
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
