import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUncertainty } from './useUncertainty'
import type { MetricsSnapshot } from '@/lib/types'

afterEach(cleanup)

function makeMetrics(
  sessionOverrides: Record<string, unknown> = {},
  snapshotOverrides: Partial<MetricsSnapshot> = {}
): MetricsSnapshot {
  const session: Record<string, unknown> = {
    interruption_count: 0,
    recent_interruptions: 0,
    hard_interruption_count: 0,
    recent_hard_interruptions: 0,
    backchannel_overlap_count: 0,
    recent_backchannel_overlaps: 0,
    echo_suspected: false,
    active_overlap_duration_current: 0,
    active_overlap_state: 'none',
    tutor_cutoffs: 0,
    student_cutoffs: 0,
    silence_duration_current: 0,
    time_since_student_spoke: 0,
    mutual_silence_duration_current: 0,
    tutor_monologue_duration_current: 0,
    tutor_turn_count: 0,
    student_turn_count: 0,
    student_response_latency_last_seconds: 0,
    tutor_response_latency_last_seconds: 0,
    recent_tutor_talk_percent: 0,
    engagement_trend: 'stable' as const,
    engagement_score: 0.5,
    ...sessionOverrides,
  }

  return {
    timestamp: new Date().toISOString(),
    session_id: 'test-session',
    tutor: {} as MetricsSnapshot['tutor'],
    student: {} as MetricsSnapshot['student'],
    session: session as unknown as MetricsSnapshot['session'],
    degraded: false,
    gaze_unavailable: false,
    server_processing_ms: 10,
    latency_p50_ms: 20,
    latency_p95_ms: 40,
    degradation_reason: '',
    target_fps: 30,
    ...snapshotOverrides,
  }
}

function TestHarness({
  onReady,
}: {
  onReady: (api: ReturnType<typeof useUncertainty>) => void
}) {
  const api = useUncertainty()
  onReady(api)

  return (
    <div>
      <div data-testid="score">
        {api.uncertainty.score !== null ? api.uncertainty.score : 'null'}
      </div>
      <div data-testid="topic">
        {api.uncertainty.topic ?? 'null'}
      </div>
      <div data-testid="confidence">
        {api.uncertainty.confidence !== null
          ? api.uncertainty.confidence
          : 'null'}
      </div>
      <div data-testid="visible">
        {api.uncertainty.visible ? 'yes' : 'no'}
      </div>
    </div>
  )
}

describe('useUncertainty', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts with no uncertainty', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    expect(screen.getByTestId('score')).toHaveTextContent('null')
    expect(screen.getByTestId('visible')).toHaveTextContent('no')
    expect(api.uncertainty.score).toBeNull()
  })

  it('shows uncertainty when score is above threshold', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({}, {
          student_uncertainty_score: 0.75,
          student_uncertainty_topic: 'derivatives',
          student_uncertainty_confidence: 0.9,
        })
      )
    })

    expect(screen.getByTestId('score')).toHaveTextContent('0.75')
    expect(screen.getByTestId('topic')).toHaveTextContent('derivatives')
    expect(screen.getByTestId('confidence')).toHaveTextContent('0.9')
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')
  })

  it('prefers top-level uncertainty fields from MetricsSnapshot', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics(
          {
            student_uncertainty_score: 0.2,
            student_uncertainty_topic: 'stale-session-field',
            student_uncertainty_confidence: 0.3,
          },
          {
            student_uncertainty_score: 0.88,
            student_uncertainty_topic: 'limits',
            student_uncertainty_confidence: 0.93,
          }
        )
      )
    })

    expect(screen.getByTestId('score')).toHaveTextContent('0.88')
    expect(screen.getByTestId('topic')).toHaveTextContent('limits')
    expect(screen.getByTestId('confidence')).toHaveTextContent('0.93')
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')
  })

  it('ignores scores below the threshold', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({
          student_uncertainty_score: 0.05,
          student_uncertainty_topic: 'algebra',
        })
      )
    })

    expect(screen.getByTestId('visible')).toHaveTextContent('no')
  })

  it('enforces minimum display duration (3s) before hiding', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    // Show uncertainty
    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({
          student_uncertainty_score: 0.8,
          student_uncertainty_topic: 'integrals',
          student_uncertainty_confidence: 0.85,
        })
      )
    })

    expect(screen.getByTestId('visible')).toHaveTextContent('yes')

    // Clear uncertainty after 1s (before minimum duration)
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    act(() => {
      api.handleUncertaintyMetrics(makeMetrics({}))
    })

    // Still visible due to minimum display duration
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')

    // Advance past the remaining 2s
    act(() => {
      vi.advanceTimersByTime(2100)
    })

    expect(screen.getByTestId('visible')).toHaveTextContent('no')
  })

  it('hides immediately if minimum duration already elapsed', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    // Show uncertainty
    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({
          student_uncertainty_score: 0.6,
          student_uncertainty_topic: 'fractions',
          student_uncertainty_confidence: 0.7,
        })
      )
    })

    expect(screen.getByTestId('visible')).toHaveTextContent('yes')

    // Wait past minimum display duration
    act(() => {
      vi.advanceTimersByTime(3500)
    })

    // Clear uncertainty
    act(() => {
      api.handleUncertaintyMetrics(makeMetrics({}))
    })

    expect(screen.getByTestId('visible')).toHaveTextContent('no')
  })

  it('resets hide timer when new uncertainty arrives during min-duration hold', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    // Show uncertainty
    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({ student_uncertainty_score: 0.8, student_uncertainty_topic: 'A' })
      )
    })

    // Clear after 1s
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    act(() => {
      api.handleUncertaintyMetrics(makeMetrics({}))
    })
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')

    // New uncertainty arrives during hold period
    act(() => {
      vi.advanceTimersByTime(500)
    })
    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({ student_uncertainty_score: 0.9, student_uncertainty_topic: 'B' })
      )
    })

    expect(screen.getByTestId('score')).toHaveTextContent('0.9')
    expect(screen.getByTestId('topic')).toHaveTextContent('B')
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')

    // The old timer should have been cleared; uncertainty remains visible
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')
  })

  it('handles metrics with no uncertainty fields gracefully', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleUncertaintyMetrics(makeMetrics({}))
    })

    expect(screen.getByTestId('score')).toHaveTextContent('null')
    expect(screen.getByTestId('visible')).toHaveTextContent('no')
  })

  it('updates score values while keeping visible during transition', () => {
    let api!: ReturnType<typeof useUncertainty>
    render(<TestHarness onReady={(a) => { api = a }} />)

    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({ student_uncertainty_score: 0.5, student_uncertainty_topic: 'X' })
      )
    })

    act(() => {
      api.handleUncertaintyMetrics(
        makeMetrics({ student_uncertainty_score: 0.9, student_uncertainty_topic: 'Y' })
      )
    })

    expect(screen.getByTestId('score')).toHaveTextContent('0.9')
    expect(screen.getByTestId('topic')).toHaveTextContent('Y')
    expect(screen.getByTestId('visible')).toHaveTextContent('yes')
  })
})
