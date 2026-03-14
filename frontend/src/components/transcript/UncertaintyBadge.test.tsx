import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { UncertaintyBadge } from './UncertaintyBadge'

afterEach(() => {
  cleanup()
})

describe('UncertaintyBadge', () => {
  it('renders with topic text', () => {
    render(<UncertaintyBadge topic="algebra" />)
    const badge = screen.getByTestId('uncertainty-badge')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('🔶')
    expect(badge).toHaveTextContent('algebra')
  })

  it('shows "uncertain" as default label when no topic is provided', () => {
    render(<UncertaintyBadge />)
    const badge = screen.getByTestId('uncertainty-badge')
    expect(badge).toHaveTextContent('uncertain')
  })

  it('includes score percentage in title attribute', () => {
    render(<UncertaintyBadge topic="fractions" score={0.85} />)
    const badge = screen.getByTestId('uncertainty-badge')
    expect(badge).toHaveAttribute('title', 'Uncertainty: fractions (85%)')
  })

  it('shows title without percentage when score is not provided', () => {
    render(<UncertaintyBadge topic="geometry" />)
    const badge = screen.getByTestId('uncertainty-badge')
    expect(badge).toHaveAttribute('title', 'Uncertainty: geometry')
  })

  it('rounds score percentage correctly', () => {
    render(<UncertaintyBadge topic="calculus" score={0.333} />)
    const badge = screen.getByTestId('uncertainty-badge')
    expect(badge).toHaveAttribute('title', 'Uncertainty: calculus (33%)')
  })
})
