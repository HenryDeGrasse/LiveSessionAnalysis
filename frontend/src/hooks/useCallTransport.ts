'use client'

import { useMemo } from 'react'
import { usePeerConnection } from '@/hooks/usePeerConnection'
import { useLiveKitTransport } from '@/hooks/useLiveKitTransport'
import type { MediaProvider } from '@/lib/types'

type SessionRole = 'tutor' | 'student'

interface UseCallTransportOptions {
  provider: MediaProvider
  enabled: boolean
  role: SessionRole | null
  localStream: MediaStream | null
  sessionId: string
  sessionToken: string
  sendSignal: (signal: {
    signal_type: 'offer' | 'answer' | 'ice_candidate'
    payload: Record<string, unknown>
  }) => void
  onDebugEvent?: (message: string) => void
}

export function useCallTransport({
  provider,
  enabled,
  role,
  localStream,
  sessionId,
  sessionToken,
  sendSignal,
  onDebugEvent,
}: UseCallTransportOptions) {
  const peerTransport = usePeerConnection({
    enabled: enabled && provider === 'custom_webrtc',
    role,
    localStream,
    sendSignal,
    onDebugEvent,
  })

  const liveKitTransport = useLiveKitTransport({
    enabled: enabled && provider === 'livekit',
    role,
    localStream,
    sessionId,
    sessionToken,
    onDebugEvent,
  })

  return useMemo(() => {
    return provider === 'livekit' ? liveKitTransport : peerTransport
  }, [provider, liveKitTransport, peerTransport])
}
