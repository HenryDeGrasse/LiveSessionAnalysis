'use client'

import { useCallback, useState } from 'react'
import type { MetricsSnapshot } from '@/lib/types'

export function useMetrics() {
  const [currentMetrics, setCurrentMetrics] = useState<MetricsSnapshot | null>(null)
  const [metricsHistory, setMetricsHistory] = useState<MetricsSnapshot[]>([])

  const handleMetrics = useCallback((data: MetricsSnapshot) => {
    setCurrentMetrics(data)
    setMetricsHistory((prev) => [...prev.slice(-299), data])
  }, [])

  return { currentMetrics, metricsHistory, handleMetrics }
}
