'use client'

import { useCallback, useState } from 'react'
import type { AISuggestion } from '@/lib/types'
import { apiFetch } from '@/lib/api-client'

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

/**
 * Manages on-demand AI coaching suggestions.
 *
 * - Fetches suggestions via `POST /api/sessions/{id}/suggest`
 * - Submits feedback via `POST /api/sessions/{id}/suggestion-feedback`
 * - Tracks loading/error states and suggestion history
 */
export function useAISuggestion({
  sessionId,
  accessToken,
}: UseAISuggestionOptions): UseAISuggestionReturn {
  const [suggestion, setSuggestion] = useState<AISuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [callsRemaining, setCallsRemaining] = useState<number | null>(null)
  const [history, setHistory] = useState<SuggestionHistoryEntry[]>([])

  const requestSuggestion = useCallback(async () => {
    if (loading) return

    setLoading(true)
    setError(null)

    try {
      const tokenParam = accessToken ? `?token=${encodeURIComponent(accessToken)}` : ''
      const resp = await apiFetch(
        `/api/sessions/${sessionId}/suggest${tokenParam}`,
        { method: 'POST', accessToken }
      )

      if (resp.status === 429) {
        setSuggestion(null)
        setError('Suggestion budget exhausted. Please wait before requesting again.')
        return
      }

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setSuggestion(null)
        setError(body.detail || `Request failed (${resp.status})`)
        return
      }

      const body = await resp.json()

      if (typeof body.calls_remaining === 'number') {
        setCallsRemaining(body.calls_remaining)
      }

      if (body.status === 'no_suggestion') {
        setSuggestion(null)
        setError('No suggestion available at this time.')
        return
      }

      if (body.suggestion) {
        const sug: AISuggestion = {
          id: body.suggestion.id ?? '',
          topic: body.suggestion.topic ?? '',
          observation: body.suggestion.observation ?? '',
          suggestion: body.suggestion.suggestion ?? '',
          suggested_prompt: body.suggestion.suggested_prompt ?? '',
          priority: body.suggestion.priority ?? 'medium',
          confidence: body.suggestion.confidence ?? 0,
        }

        setSuggestion(sug)
        setHistory((prev) => [
          ...prev,
          { suggestion: sug, timestamp: Date.now() },
        ])
      }
    } catch (err) {
      setSuggestion(null)
      setError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setLoading(false)
    }
  }, [sessionId, accessToken, loading])

  const submitFeedback = useCallback(
    async (suggestionId: string, helpful: boolean) => {
      try {
        const tokenParam = accessToken
          ? `?token=${encodeURIComponent(accessToken)}`
          : ''
        const resp = await apiFetch(
          `/api/sessions/${sessionId}/suggestion-feedback${tokenParam}`,
          {
            method: 'POST',
            accessToken,
            body: JSON.stringify({ suggestion_id: suggestionId, helpful }),
          }
        )

        if (resp.ok) {
          // Update history with feedback
          setHistory((prev) =>
            prev.map((entry) =>
              entry.suggestion.id === suggestionId
                ? { ...entry, feedback: { helpful } }
                : entry
            )
          )
        }
      } catch {
        // Feedback submission is best-effort; don't surface errors to the user
      }
    },
    [sessionId, accessToken]
  )

  const clearSuggestion = useCallback(() => {
    setSuggestion(null)
    setError(null)
  }, [])

  return {
    suggestion,
    loading,
    error,
    callsRemaining,
    history,
    requestSuggestion,
    submitFeedback,
    clearSuggestion,
  }
}
