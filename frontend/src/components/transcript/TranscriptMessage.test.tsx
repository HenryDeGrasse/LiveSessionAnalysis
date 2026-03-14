import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TranscriptMessage } from './TranscriptMessage'
import type { TranscriptMessage as TranscriptMessageData } from '@/lib/types'

afterEach(() => {
  cleanup()
})

function makeMessage(overrides: Partial<TranscriptMessageData> = {}): TranscriptMessageData {
  return {
    utterance_id: 'u-1',
    revision: 1,
    role: 'student',
    text: 'I think the answer is 42',
    start_time: 65,
    end_time: 68,
    is_partial: false,
    ...overrides,
  }
}

describe('TranscriptMessage', () => {
  it('renders a final message with speaker label, timestamp, and text', () => {
    render(<TranscriptMessage message={makeMessage()} />)
    const el = screen.getByTestId('transcript-message')
    expect(el).toBeInTheDocument()
    expect(el).toHaveTextContent('Student:')
    expect(el).toHaveTextContent('01:05')
    expect(el).toHaveTextContent('I think the answer is 42')
  })

  it('displays tutor label for tutor role', () => {
    render(<TranscriptMessage message={makeMessage({ role: 'tutor' })} />)
    const el = screen.getByTestId('transcript-message')
    expect(el).toHaveTextContent('Tutor:')
  })

  it('shows UncertaintyBadge when uncertainty_score is present', () => {
    render(
      <TranscriptMessage
        message={makeMessage({
          uncertainty_score: 0.7,
          uncertainty_topic: 'derivatives',
        })}
      />
    )
    expect(screen.getByTestId('uncertainty-badge')).toBeInTheDocument()
    expect(screen.getByTestId('uncertainty-badge')).toHaveTextContent('derivatives')
  })

  it('does not show UncertaintyBadge when uncertainty_score is 0', () => {
    render(
      <TranscriptMessage
        message={makeMessage({ uncertainty_score: 0 })}
      />
    )
    expect(screen.queryByTestId('uncertainty-badge')).not.toBeInTheDocument()
  })

  it('does not show UncertaintyBadge when uncertainty_score is undefined', () => {
    render(<TranscriptMessage message={makeMessage()} />)
    expect(screen.queryByTestId('uncertainty-badge')).not.toBeInTheDocument()
  })

  it('renders partial messages using PartialTranscript', () => {
    render(
      <TranscriptMessage
        message={makeMessage({ is_partial: true, text: 'I think' })}
      />
    )
    expect(screen.getByTestId('partial-transcript')).toBeInTheDocument()
    expect(screen.getByTestId('partial-transcript')).toHaveTextContent('I think')
    expect(screen.queryByTestId('transcript-message')).not.toBeInTheDocument()
  })

  it('formats timestamps with leading zeros', () => {
    render(<TranscriptMessage message={makeMessage({ start_time: 5 })} />)
    const el = screen.getByTestId('transcript-message')
    expect(el).toHaveTextContent('00:05')
  })
})
