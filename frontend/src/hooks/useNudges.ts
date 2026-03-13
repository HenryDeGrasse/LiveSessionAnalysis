'use client'

import { useCallback, useRef, useState } from 'react'
import type { Nudge } from '@/lib/types'

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

  // Keep a stable ref so handleNudge always reads the current sound preference
  // without needing it in its dependency array
  const nudgeSoundEnabledRef = useRef(nudgeSoundEnabled)
  nudgeSoundEnabledRef.current = nudgeSoundEnabled

  const handleNudge = useCallback(
    (data: Nudge) => {
      setNudgeHistory((prev) => [...prev, data])
      if (!nudgesEnabled) return
      setNudges((prev) => [...prev, data])
      if (nudgeSoundEnabledRef.current) {
        playNudgeChime()
      }
    },
    [nudgesEnabled]
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

  return {
    nudges,
    nudgeHistory,
    nudgesEnabled,
    nudgeSoundEnabled,
    handleNudge,
    dismissNudge,
    disableAllNudges,
    enableAllNudges,
    toggleNudgeSound,
  }
}
