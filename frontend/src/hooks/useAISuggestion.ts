'use client'

import { useCallback, useRef, useState } from 'react'
import type { AISuggestion } from '@/lib/types'
import { API_URL } from '@/lib/constants'

export interface SuggestionHistoryEntry {
  suggestion: AISuggestion
  timestamp: number
  feedback?: { helpful: boolean }
}

export interface UseAISuggestionOptions {
  /** Session ID for API calls. */
  sessionId: string
  /** Backend auth token (tutor token or JWT). */
  accessToken?: string
}

export interface UseAISuggestionReturn {
  /** The most recently fetched suggestion, or null. */
  suggestion: AISuggestion | null
  /** True while a suggestion request is in flight. */
  loading: boolean
  /** Streaming text as it arrives from the LLM. */
  streamingText: string
  /** Error message from the last failed request, or null. */
  error: string | null
  /** Remaining API calls in the current budget window. */
  callsRemaining: number | null
  /** History of all suggestions received this session. */
  history: SuggestionHistoryEntry[]
  /** Request a new on-demand suggestion from the backend. */
  requestSuggestion: () => Promise<void>
  /** Submit feedback for a suggestion. */
  submitFeedback: (suggestionId: string, helpful: boolean) => Promise<void>
  /** Clear the current suggestion (dismiss). */
  clearSuggestion: () => void
}

function getBaseUrl(): string {
  return API_URL
}

/**
 * Manages on-demand AI coaching suggestions with SSE streaming.
 *
 * - Streams tokens via SSE for real-time display (~400ms to first token)
 * - Falls back to JSON if SSE is unavailable
 * - Submits feedback via POST
 */
export function useAISuggestion({
  sessionId,
  accessToken,
}: UseAISuggestionOptions): UseAISuggestionReturn {
  const [suggestion, setSuggestion] = useState<AISuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [callsRemaining, setCallsRemaining] = useState<number | null>(null)
  const [history, setHistory] = useState<SuggestionHistoryEntry[]>([])
  const abortRef = useRef<AbortController | null>(null)

  const requestSuggestion = useCallback(async () => {
    if (loading) return

    // Cancel any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    setStreamingText('')
    setSuggestion(null)

    const tokenParam = accessToken ? `?token=${encodeURIComponent(accessToken)}` : ''
    const url = `${getBaseUrl()}/api/sessions/${sessionId}/suggest${tokenParam}`

    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'text/event-stream',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        credentials: 'include',
        signal: controller.signal,
      })

      if (resp.status === 429) {
        setError('Suggestion budget exhausted.')
        setLoading(false)
        return
      }

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setError(body.detail || `Request failed (${resp.status})`)
        setLoading(false)
        return
      }

      const contentType = resp.headers.get('content-type') || ''

      if (contentType.includes('text/event-stream')) {
        // SSE streaming path
        await _consumeSSE(resp, controller.signal, {
          onToken: (token) => {
            setStreamingText((prev) => prev + token)
          },
          onSuggestion: (result) => {
            if (typeof result.calls_remaining === 'number') {
              setCallsRemaining(result.calls_remaining)
            }
            if (result.status === 'ok' && result.suggestion) {
              const sug = _parseSuggestion(result.suggestion as Record<string, unknown>)
              setSuggestion(sug)
              setHistory((prev) => [...prev, { suggestion: sug, timestamp: Date.now() }])
            } else {
              setError((result.message as string) || 'No suggestion available.')
            }
          },
          onError: (msg) => {
            setError(msg)
          },
        })
      } else {
        // JSON fallback
        const body = await resp.json()
        if (typeof body.calls_remaining === 'number') {
          setCallsRemaining(body.calls_remaining)
        }
        if (body.status === 'ok' && body.suggestion) {
          const sug = _parseSuggestion(body.suggestion as Record<string, unknown>)
          setSuggestion(sug)
          setHistory((prev) => [...prev, { suggestion: sug, timestamp: Date.now() }])
        } else {
          setError((body.message as string) || 'No suggestion available.')
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(err instanceof Error ? err.message : 'Network error')
      }
    } finally {
      setLoading(false)
      setStreamingText('')
    }
  }, [sessionId, accessToken, loading])

  const submitFeedback = useCallback(
    async (suggestionId: string, helpful: boolean) => {
      try {
        const tokenParam = accessToken
          ? `?token=${encodeURIComponent(accessToken)}`
          : ''
        const resp = await fetch(
          `${getBaseUrl()}/api/sessions/${sessionId}/suggestion-feedback${tokenParam}`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
            },
            credentials: 'include',
            body: JSON.stringify({ suggestion_id: suggestionId, helpful }),
          }
        )

        if (resp.ok) {
          setHistory((prev) =>
            prev.map((entry) =>
              entry.suggestion.id === suggestionId
                ? { ...entry, feedback: { helpful } }
                : entry
            )
          )
        }
      } catch {
        // Best-effort
      }
    },
    [sessionId, accessToken]
  )

  const clearSuggestion = useCallback(() => {
    setSuggestion(null)
    setError(null)
    setStreamingText('')
  }, [])

  return {
    suggestion,
    loading,
    streamingText,
    error,
    callsRemaining,
    history,
    requestSuggestion,
    submitFeedback,
    clearSuggestion,
  }
}


// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

interface SSECallbacks {
  onToken: (text: string) => void
  onSuggestion: (result: Record<string, unknown>) => void
  onError: (message: string) => void
}

async function _consumeSSE(
  resp: Response,
  signal: AbortSignal,
  callbacks: SSECallbacks
): Promise<void> {
  const reader = resp.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Process complete SSE messages (double newline delimited)
      const messages = buffer.split('\n\n')
      buffer = messages.pop() || '' // Keep incomplete last message

      for (const msg of messages) {
        if (!msg.trim()) continue

        let eventType = 'message'
        let data = ''

        for (const line of msg.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            data = line.slice(6)
          }
        }

        switch (eventType) {
          case 'token':
            try {
              callbacks.onToken(JSON.parse(data))
            } catch {
              callbacks.onToken(data)
            }
            break
          case 'suggestion':
            try {
              callbacks.onSuggestion(JSON.parse(data))
            } catch {
              callbacks.onError('Failed to parse suggestion')
            }
            break
          case 'error':
            try {
              const err = JSON.parse(data)
              callbacks.onError(err.message || 'Unknown error')
            } catch {
              callbacks.onError(data || 'Unknown error')
            }
            break
          case 'done':
            return
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function _parsePriority(val: unknown): 'low' | 'medium' | 'high' {
  if (val === 'low' || val === 'medium' || val === 'high') return val
  return 'medium'
}

function _parseSuggestion(raw: Record<string, unknown>): AISuggestion {
  return {
    id: (raw.id as string) ?? '',
    topic: (raw.topic as string) ?? '',
    observation: (raw.observation as string) ?? '',
    suggestion: (raw.suggestion as string) ?? '',
    suggested_prompt: (raw.suggested_prompt as string) ?? '',
    priority: _parsePriority(raw.priority),
    confidence: (raw.confidence as number) ?? 0,
  }
}
