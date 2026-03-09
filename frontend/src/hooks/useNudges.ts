'use client'

import { useCallback, useState } from 'react'
import type { Nudge } from '@/lib/types'

export function useNudges() {
  const [nudges, setNudges] = useState<Nudge[]>([])
  const [nudgeHistory, setNudgeHistory] = useState<Nudge[]>([])
  const [nudgesEnabled, setNudgesEnabled] = useState(true)

  const handleNudge = useCallback(
    (data: Nudge) => {
      setNudgeHistory((prev) => [...prev, data])
      if (!nudgesEnabled) return
      setNudges((prev) => [...prev, data])
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

  return {
    nudges,
    nudgeHistory,
    nudgesEnabled,
    handleNudge,
    dismissNudge,
    disableAllNudges,
    enableAllNudges,
  }
}
