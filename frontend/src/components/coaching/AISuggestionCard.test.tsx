import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AISuggestionCard } from './AISuggestionCard'
import type { AISuggestion } from '@/lib/types'

afterEach(() => {
  cleanup()
})

const SAMPLE_SUGGESTION: AISuggestion = {
  id: 'sug-1',
  topic: 'fractions',
  observation: 'Student paused for 8 seconds after the fractions question',
  suggestion: 'Try using a visual representation like a pie chart',
  suggested_prompt: 'Can you draw what one-half looks like?',
  priority: 'medium',
  confidence: 0.85,
}

describe('AISuggestionCard', () => {
  it('renders the card with all sections', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    const card = screen.getByTestId('ai-suggestion-card')
    expect(card).toBeInTheDocument()
    expect(card).toHaveTextContent('AI Coaching Insight')
    expect(card).toHaveTextContent('🤖')
    expect(card).toHaveTextContent('fractions')
  })

  it('displays observation and suggestion text', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    expect(screen.getByTestId('observation-text')).toHaveTextContent(
      'Student paused for 8 seconds'
    )
    expect(screen.getByTestId('suggestion-text')).toHaveTextContent(
      'Try using a visual representation'
    )
  })

  it('renders the suggested prompt block', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    expect(screen.getByTestId('suggested-prompt-block')).toBeInTheDocument()
    expect(screen.getByTestId('suggested-prompt-text')).toHaveTextContent(
      'Can you draw what one-half looks like?'
    )
  })

  it('does not render suggested prompt block when prompt is empty', () => {
    const noPrompt = { ...SAMPLE_SUGGESTION, suggested_prompt: '' }
    render(<AISuggestionCard suggestion={noPrompt} />)

    expect(screen.queryByTestId('suggested-prompt-block')).not.toBeInTheDocument()
  })

  it('displays confidence bar with correct percentage', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    expect(screen.getByTestId('confidence-value')).toHaveTextContent('85%')
    const fill = screen.getByTestId('confidence-bar-fill')
    expect(fill).toHaveStyle({ width: '85%' })
  })

  it('calls onDismiss when dismiss button is clicked', () => {
    const onDismiss = vi.fn()
    render(
      <AISuggestionCard suggestion={SAMPLE_SUGGESTION} onDismiss={onDismiss} />
    )

    fireEvent.click(screen.getByTestId('dismiss-suggestion-btn'))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('calls onFeedback with helpful=true when thumbs up is clicked', () => {
    const onFeedback = vi.fn()
    render(
      <AISuggestionCard
        suggestion={SAMPLE_SUGGESTION}
        onFeedback={onFeedback}
      />
    )

    fireEvent.click(screen.getByTestId('feedback-helpful-btn'))
    expect(onFeedback).toHaveBeenCalledWith('sug-1', true)
  })

  it('calls onFeedback with helpful=false when thumbs down is clicked', () => {
    const onFeedback = vi.fn()
    render(
      <AISuggestionCard
        suggestion={SAMPLE_SUGGESTION}
        onFeedback={onFeedback}
      />
    )

    fireEvent.click(screen.getByTestId('feedback-unhelpful-btn'))
    expect(onFeedback).toHaveBeenCalledWith('sug-1', false)
  })

  it('shows thank you message after giving feedback', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    fireEvent.click(screen.getByTestId('feedback-helpful-btn'))

    expect(screen.getByTestId('feedback-thanks')).toHaveTextContent('👍 Thanks!')
    expect(screen.queryByTestId('feedback-helpful-btn')).not.toBeInTheDocument()
    expect(screen.queryByTestId('feedback-unhelpful-btn')).not.toBeInTheDocument()
  })

  it('shows "Noted" after negative feedback', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)

    fireEvent.click(screen.getByTestId('feedback-unhelpful-btn'))

    expect(screen.getByTestId('feedback-thanks')).toHaveTextContent('👎 Noted')
  })

  it('displays priority label', () => {
    render(<AISuggestionCard suggestion={SAMPLE_SUGGESTION} />)
    const card = screen.getByTestId('ai-suggestion-card')
    expect(card).toHaveTextContent('medium')
  })

  it('calls onUsePrompt when Use button is clicked', () => {
    const onUsePrompt = vi.fn()
    render(
      <AISuggestionCard
        suggestion={SAMPLE_SUGGESTION}
        onUsePrompt={onUsePrompt}
      />
    )

    fireEvent.click(screen.getByTestId('use-prompt-btn'))
    expect(onUsePrompt).toHaveBeenCalledWith(
      'Can you draw what one-half looks like?'
    )
  })
})
