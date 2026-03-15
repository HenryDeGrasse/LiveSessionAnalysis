'use client'

import { useCallback, useRef, useState } from 'react'
import type {
  TranscriptFinalData,
  TranscriptMessage,
  TranscriptPartialData,
  WSMessage,
} from '@/lib/types'

/** Default maximum number of transcript messages to keep in the buffer. */
const DEFAULT_BUFFER_LIMIT = 200

type TranscriptEvent =
  | TranscriptMessage
  | WSMessage
  | {
      type: 'transcript_partial' | 'transcript_final'
      data: Record<string, unknown>
    }

interface UseTranscriptOptions {
  /** Maximum number of messages to retain before trimming the oldest. */
  bufferLimit?: number
}

function isTranscriptMessage(value: unknown): value is TranscriptMessage {
  if (!value || typeof value !== 'object') return false

  const candidate = value as Partial<TranscriptMessage>
  return (
    typeof candidate.utterance_id === 'string' &&
    typeof candidate.revision === 'number' &&
    (candidate.role === 'tutor' || candidate.role === 'student') &&
    typeof candidate.text === 'string' &&
    typeof candidate.start_time === 'number' &&
    typeof candidate.end_time === 'number' &&
    typeof candidate.is_partial === 'boolean'
  )
}

function normalizeTranscriptData(
  type: 'transcript_partial' | 'transcript_final',
  data: Record<string, unknown>
): TranscriptMessage | null {
  const utterance_id = typeof data.utterance_id === 'string' ? data.utterance_id : null
  const role: TranscriptMessage['role'] | null =
    data.role === 'tutor' || data.role === 'student' ? data.role : null
  const text = typeof data.text === 'string' ? data.text : null

  if (!utterance_id || !role || text === null) {
    return null
  }

  const sessionTime =
    typeof data.start_time === 'number'
      ? data.start_time
      : typeof data.session_time === 'number'
        ? data.session_time
        : 0

  const endTime =
    typeof data.end_time === 'number'
      ? data.end_time
      : typeof data.session_time === 'number'
        ? data.session_time
        : sessionTime

  const baseMessage = {
    utterance_id,
    revision: typeof data.revision === 'number' ? data.revision : 0,
    role,
    text,
    start_time: sessionTime,
    end_time: endTime,
    uncertainty_score:
      typeof data.uncertainty_score === 'number' ? data.uncertainty_score : undefined,
    uncertainty_topic:
      typeof data.uncertainty_topic === 'string' ? data.uncertainty_topic : undefined,
    sentiment: typeof data.sentiment === 'string' ? data.sentiment : undefined,
  }

  if (type === 'transcript_partial') {
    const partial: TranscriptPartialData = {
      ...baseMessage,
      is_partial: true,
      revision: typeof data.revision === 'number' ? data.revision : 1,
      end_time: endTime,
    }
    return partial
  }

  const final: TranscriptFinalData = {
    ...baseMessage,
    is_partial: false,
  }
  return final
}

function toTranscriptMessage(event: TranscriptEvent): TranscriptMessage | null {
  if (isTranscriptMessage(event)) {
    return event
  }

  if (
    event &&
    typeof event === 'object' &&
    'type' in event &&
    (event.type === 'transcript_partial' || event.type === 'transcript_final') &&
    'data' in event &&
    event.data &&
    typeof event.data === 'object'
  ) {
    return normalizeTranscriptData(event.type, event.data as Record<string, unknown>)
  }

  return null
}

/**
 * Manages real-time transcript state.
 *
 * - Maintains a `Map<utterance_id, TranscriptMessage>` internally.
 * - Partial updates upsert the entry; final messages replace the entry.
 * - Auto-trims the oldest messages when the buffer exceeds `bufferLimit`.
 * - Exposes a `messages` array sorted ascending by `start_time`.
 *
 * Works with both WebSocket (`transcript_partial` / `transcript_final`)
 * and LiveKit data-packet sources.
 */
export function useTranscript(options?: UseTranscriptOptions) {
  const bufferLimit = options?.bufferLimit ?? DEFAULT_BUFFER_LIMIT

  const mapRef = useRef<Map<string, TranscriptMessage>>(new Map())
  const [messages, setMessages] = useState<TranscriptMessage[]>([])

  const rebuildSorted = useCallback(() => {
    const sorted = Array.from(mapRef.current.values()).sort(
      (a, b) => a.start_time - b.start_time
    )
    setMessages(sorted)
  }, [])

  const trimOldest = useCallback(() => {
    const map = mapRef.current
    if (map.size <= bufferLimit) return

    // Map preserves insertion order — delete the earliest-inserted entries.
    const excess = map.size - bufferLimit
    const keys = map.keys()
    for (let i = 0; i < excess; i++) {
      const next = keys.next()
      if (!next.done) {
        map.delete(next.value)
      }
    }
  }, [bufferLimit])

  const applyTranscriptMessage = useCallback(
    (msg: TranscriptMessage) => {
      const map = mapRef.current
      const existing = map.get(msg.utterance_id)

      if (msg.is_partial && existing && !existing.is_partial) {
        // Don't overwrite a finalized message with a partial.
        return
      }

      if (msg.is_partial && existing && existing.revision > msg.revision) {
        // Ignore stale partial revisions.
        return
      }

      // Delete first so re-insertion moves the key to the end (preserves
      // insertion-order trimming semantics).
      map.delete(msg.utterance_id)
      map.set(msg.utterance_id, msg)

      trimOldest()
      rebuildSorted()
    },
    [trimOldest, rebuildSorted]
  )

  const handleTranscriptMessage = useCallback(
    (event: TranscriptEvent) => {
      const msg = toTranscriptMessage(event)
      if (!msg) return
      applyTranscriptMessage(msg)
    },
    [applyTranscriptMessage]
  )

  const handleTranscriptPacket = useCallback(
    (topic: string, payload: Uint8Array) => {
      if (
        topic !== 'lsa.transcript.partial.v1' &&
        topic !== 'lsa.transcript.final.v1'
      ) {
        return
      }

      try {
        const text = new TextDecoder().decode(payload)
        const event = JSON.parse(text) as TranscriptEvent
        handleTranscriptMessage(event)
      } catch {
        // Ignore malformed transcript packets.
      }
    },
    [handleTranscriptMessage]
  )

  const clearTranscript = useCallback(() => {
    mapRef.current.clear()
    setMessages([])
  }, [])

  return {
    messages,
    handleTranscriptMessage,
    handleTranscriptPacket,
    clearTranscript,
  }
}
