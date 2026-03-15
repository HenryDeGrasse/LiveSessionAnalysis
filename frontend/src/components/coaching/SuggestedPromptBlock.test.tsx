import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SuggestedPromptBlock } from './SuggestedPromptBlock'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SuggestedPromptBlock', () => {
  it('renders the prompt text', () => {
    render(<SuggestedPromptBlock prompt="Can you explain that differently?" />)

    expect(screen.getByTestId('suggested-prompt-block')).toBeInTheDocument()
    expect(screen.getByTestId('suggested-prompt-text')).toHaveTextContent(
      'Can you explain that differently?'
    )
  })

  it('renders Copy button', () => {
    render(<SuggestedPromptBlock prompt="test prompt" />)

    expect(screen.getByTestId('copy-prompt-btn')).toHaveTextContent('Copy')
  })

  it('does not render Use button when onUse is not provided', () => {
    render(<SuggestedPromptBlock prompt="test prompt" />)

    expect(screen.queryByTestId('use-prompt-btn')).not.toBeInTheDocument()
  })

  it('renders Use button when onUse is provided', () => {
    render(<SuggestedPromptBlock prompt="test prompt" onUse={vi.fn()} />)

    expect(screen.getByTestId('use-prompt-btn')).toBeInTheDocument()
    expect(screen.getByTestId('use-prompt-btn')).toHaveTextContent('Use')
  })

  it('calls onUse with the prompt when Use is clicked', () => {
    const onUse = vi.fn()
    render(<SuggestedPromptBlock prompt="Try this approach" onUse={onUse} />)

    fireEvent.click(screen.getByTestId('use-prompt-btn'))
    expect(onUse).toHaveBeenCalledWith('Try this approach')
  })

  it('copies text to clipboard when Copy is clicked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: { writeText },
    })

    render(<SuggestedPromptBlock prompt="Copy me" />)

    fireEvent.click(screen.getByTestId('copy-prompt-btn'))
    expect(writeText).toHaveBeenCalledWith('Copy me')
  })
})
