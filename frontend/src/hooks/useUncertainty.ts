'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { MetricsSnapshot } from '@/lib/types'

/** Minimum display duration (ms) to prevent flash of uncertainty indicators. */
const MIN_DISPLAY_DURATION_MS = 3_000

/** Threshold below which uncertainty is considered absent. */
const UNCERTAINTY_THRESHOLD = 0.1

export interface UncertaintyState {
  /** Current student uncertainty score (0–1), or null when absent. */
  score: number | null
  /** Topic the student is uncertain about, or null. */
  topic: string | null
  /** Confidence in the uncertainty detection (0–1), or null. */
  confidence: number | null
  /** Whether the uncertainty indicator should be visibly displayed. */
  visible: boolean
}

/**
 * Extracts student uncertainty signals from MetricsSnapshot updates.
 *
 * - Reads `student_uncertainty_score`, `student_uncertainty_topic`, and
 *   `student_uncertainty_confidence` from the session-level metrics.
 * - Applies a minimum display duration (3 s) to prevent flash.
 * - Smooths transitions so the indicator stays visible for at least the
 *   minimum duration once triggered.
 */
export function useUncertainty() {
  const [state, setState] = useState<UncertaintyState>({
    score: null,
    topic: null,
    confidence: null,
    visible: false,
  })

  const visibleSinceRef = useRef<number | null>(null)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (hideTimerRef.current !== null) {
        clearTimeout(hideTimerRef.current)
      }
    }
  }, [])

  const handleMetrics = useCallback((snapshot: MetricsSnapshot) => {
    const session = snapshot.session as unknown as Record<string, unknown>

    const rawScore =
      typeof snapshot.student_uncertainty_score === 'number'
        ? snapshot.student_uncertainty_score
        : typeof session.student_uncertainty_score === 'number'
          ? session.student_uncertainty_score
          : null
    const rawTopic =
      typeof snapshot.student_uncertainty_topic === 'string'
        ? snapshot.student_uncertainty_topic
        : typeof session.student_uncertainty_topic === 'string'
          ? session.student_uncertainty_topic
          : null
    const rawConfidence =
      typeof snapshot.student_uncertainty_confidence === 'number'
        ? snapshot.student_uncertainty_confidence
        : typeof session.student_uncertainty_confidence === 'number'
          ? session.student_uncertainty_confidence
          : null

    const isUncertain = rawScore !== null && rawScore >= UNCERTAINTY_THRESHOLD

    if (isUncertain) {
      // Clear any pending hide timer — we have fresh uncertainty
      if (hideTimerRef.current !== null) {
        clearTimeout(hideTimerRef.current)
        hideTimerRef.current = null
      }

      if (visibleSinceRef.current === null) {
        visibleSinceRef.current = Date.now()
      }

      setState({
        score: rawScore,
        topic: rawTopic,
        confidence: rawConfidence,
        visible: true,
      })
    } else {
      // Uncertainty cleared — enforce minimum display duration
      const visibleSince = visibleSinceRef.current
      if (visibleSince !== null) {
        const elapsed = Date.now() - visibleSince
        const remaining = MIN_DISPLAY_DURATION_MS - elapsed

        if (remaining > 0 && hideTimerRef.current === null) {
          // Keep visible for the remainder, then hide
          hideTimerRef.current = setTimeout(() => {
            visibleSinceRef.current = null
            hideTimerRef.current = null
            setState({
              score: null,
              topic: null,
              confidence: null,
              visible: false,
            })
          }, remaining)

          // Update score values but keep visible
          setState({
            score: rawScore,
            topic: rawTopic,
            confidence: rawConfidence,
            visible: true,
          })
        } else if (remaining <= 0) {
          // Minimum duration already elapsed — hide immediately
          visibleSinceRef.current = null
          setState({
            score: null,
            topic: null,
            confidence: null,
            visible: false,
          })
        }
        // If hideTimerRef.current is already set, do nothing — timer will handle it
      } else {
        // Was never visible — stay hidden
        setState({
          score: null,
          topic: null,
          confidence: null,
          visible: false,
        })
      }
    }
  }, [])

  return { uncertainty: state, handleUncertaintyMetrics: handleMetrics }
}
