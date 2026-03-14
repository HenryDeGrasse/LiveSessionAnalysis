'use client'

import { useCallback, useRef, useState } from 'react'
import type { AISuggestion, Nudge } from '@/lib/types'

/**
 * Synthesizes a short, non-intrusive notification chime using the Web Audio API.
 * A sine wave at ~880 Hz for 150 ms with a fast linear fade-out — no external
 * audio file required.
 */
function playNudgeChime(): void {
  try {
    const AudioContextClass =
      window.AudioContext ??
      (window as Window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext
    if (!AudioContextClass) return

    const ctx = new AudioContextClass()
    const oscillator = ctx.createOscillator()
    const gainNode = ctx.createGain()

    oscillator.connect(gainNode)
    gainNode.connect(ctx.destination)

    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(880, ctx.currentTime)

    // Quick fade-out: start at 0.18 volume, ramp to 0 over 150 ms
    gainNode.gain.setValueAtTime(0.18, ctx.currentTime)
    gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.15)

    oscillator.start(ctx.currentTime)
    oscillator.stop(ctx.currentTime + 0.15)

    // Clean up AudioContext after playback to avoid resource leaks
    oscillator.onended = () => {
      ctx.close().catch(() => {})
    }
  } catch {
    // Silently ignore — audio is a non-critical enhancement
  }
}

export function useNudges() {
  const [nudges, setNudges] = useState<Nudge[]>([])
  const [nudgeHistory, setNudgeHistory] = useState<Nudge[]>([])
  const [nudgesEnabled, setNudgesEnabled] = useState(true)
  const [nudgeSoundEnabled, setNudgeSoundEnabled] = useState(true)
  const [aiSuggestionFromNudge, setAiSuggestionFromNudge] = useState<AISuggestion | null>(null)

  // Keep stable refs so handleNudge always reads the current preferences
  // without needing them in its dependency array (avoids cascade re-renders
  // that would tear down the WebSocket connection).
  const nudgeSoundEnabledRef = useRef(nudgeSoundEnabled)
  nudgeSoundEnabledRef.current = nudgeSoundEnabled

  const nudgesEnabledRef = useRef(nudgesEnabled)
  nudgesEnabledRef.current = nudgesEnabled

  const handleNudge = useCallback(
    (data: Nudge) => {
      setNudgeHistory((prev) => [...prev, data])
      if (!nudgesEnabledRef.current) return

      // AI coaching suggestions are routed to a dedicated state instead of
      // the standard nudge list, so they can be rendered via AISuggestionCard.
      if (data.nudge_type === 'ai_coaching_suggestion') {
        const metrics = data.trigger_metrics as Record<string, unknown>
        const suggestionText =
          typeof metrics.suggestion === 'string' && metrics.suggestion.trim().length > 0
            ? metrics.suggestion
            : data.message
        const suggestion: AISuggestion = {
          id:
            typeof metrics.suggestion_id === 'string' && metrics.suggestion_id.length > 0
              ? metrics.suggestion_id
              : data.id,
          topic: typeof metrics.topic === 'string' ? metrics.topic : '',
          observation:
            typeof metrics.observation === 'string' && metrics.observation.trim().length > 0
              ? metrics.observation
              : suggestionText,
          suggestion: suggestionText,
          suggested_prompt:
            typeof metrics.suggested_prompt === 'string'
              ? metrics.suggested_prompt
              : '',
          priority: data.priority as AISuggestion['priority'],
          confidence:
            typeof metrics.confidence === 'number' ? metrics.confidence : 0,
        }
        setAiSuggestionFromNudge(suggestion)
        if (nudgeSoundEnabledRef.current) {
          playNudgeChime()
        }
        return
      }

      setNudges((prev) => [...prev, data])
      if (nudgeSoundEnabledRef.current) {
        playNudgeChime()
      }
    },
    [] // stable — reads from refs
  )

  const dismissNudge = useCallback((id: string) => {
    setNudges((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const disableAllNudges = useCallback(() => {
    setNudgesEnabled(false)
    setNudges([])
  }, [])

  const enableAllNudges = useCallback(() => {
    setNudgesEnabled(true)
  }, [])

  const toggleNudgeSound = useCallback(() => {
    setNudgeSoundEnabled((prev) => !prev)
  }, [])

  const clearAiSuggestionFromNudge = useCallback(() => {
    setAiSuggestionFromNudge(null)
  }, [])

  return {
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
  }
}
