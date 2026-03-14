import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SuggestButton } from './SuggestButton'

afterEach(() => {
  cleanup()
})

describe('SuggestButton', () => {
  it('renders with default label and icon', () => {
    render(<SuggestButton loading={false} onClick={vi.fn()} />)

    const btn = screen.getByTestId('suggest-button')
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveTextContent('Get AI Suggestion')
    expect(btn).toHaveTextContent('🤖')
    expect(btn).not.toBeDisabled()
  })

  it('shows loading state with spinner', () => {
    render(<SuggestButton loading={true} onClick={vi.fn()} />)

    const btn = screen.getByTestId('suggest-button')
    expect(btn).toHaveTextContent('Thinking…')
    expect(btn).toBeDisabled()
    expect(screen.getByTestId('suggest-button-spinner')).toBeInTheDocument()
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<SuggestButton loading={false} onClick={onClick} />)

    fireEvent.click(screen.getByTestId('suggest-button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('does not call onClick when loading', () => {
    const onClick = vi.fn()
    render(<SuggestButton loading={true} onClick={onClick} />)

    fireEvent.click(screen.getByTestId('suggest-button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('displays calls remaining badge', () => {
    render(
      <SuggestButton loading={false} onClick={vi.fn()} callsRemaining={3} />
    )

    expect(screen.getByTestId('calls-remaining-badge')).toHaveTextContent('3')
  })

  it('does not show badge when callsRemaining is null', () => {
    render(
      <SuggestButton loading={false} onClick={vi.fn()} callsRemaining={null} />
    )

    expect(screen.queryByTestId('calls-remaining-badge')).not.toBeInTheDocument()
  })

  it('is disabled when disabled prop is true', () => {
    render(
      <SuggestButton loading={false} onClick={vi.fn()} disabled={true} />
    )

    expect(screen.getByTestId('suggest-button')).toBeDisabled()
  })
})
