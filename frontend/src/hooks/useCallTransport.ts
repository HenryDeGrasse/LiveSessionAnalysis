'use client'

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
  onDataPacket?: (topic: string, payload: Uint8Array) => void
}

/**
 * Unified call transport hook.
 *
 * The legacy custom_webrtc transport has been removed.  All sessions now use
 * LiveKit for media transport.  The `provider` and `sendSignal` parameters
 * are kept for backward compatibility with the session page interface but
 * are no longer used to select a transport implementation.
 */
export function useCallTransport({
  enabled,
  role,
  localStream,
  sessionId,
  sessionToken,
  onDebugEvent,
  onDataPacket,
}: UseCallTransportOptions) {
  return useLiveKitTransport({
    enabled,
    role,
    localStream,
    sessionId,
    sessionToken,
    onDebugEvent,
    onDataPacket,
  })
}
