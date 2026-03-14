'use client'

import { useCallback, useState } from 'react'
import type { AISuggestion } from '@/lib/types'
import { SuggestedPromptBlock } from './SuggestedPromptBlock'

interface AISuggestionCardProps {
  /** The AI suggestion to display. */
  suggestion: AISuggestion
  /** Called when the tutor dismisses the card. */
  onDismiss?: () => void
  /** Called when the tutor submits feedback (thumbs up/down). */
  onFeedback?: (suggestionId: string, helpful: boolean) => void
  /** Called when the tutor clicks "Use" on the suggested prompt. */
  onUsePrompt?: (prompt: string) => void
}

const priorityColors: Record<string, string> = {
  high: 'text-red-300',
  medium: 'text-amber-300',
  low: 'text-slate-400',
}

/**
 * Displays an AI coaching insight card with:
 * - 🤖 icon and violet border to distinguish from rule-based nudges
 * - Observation text explaining what the AI noticed
 * - Suggestion text with recommended tutor action
 * - SuggestedPromptBlock with Copy/Use buttons
 * - Confidence bar
 * - 👍/👎 feedback buttons
 * - Dismissible via ✕ button
 */
export function AISuggestionCard({
  suggestion,
  onDismiss,
  onFeedback,
  onUsePrompt,
}: AISuggestionCardProps) {
  const [feedbackGiven, setFeedbackGiven] = useState<boolean | null>(null)

  const handleFeedback = useCallback(
    (helpful: boolean) => {
      setFeedbackGiven(helpful)
      onFeedback?.(suggestion.id, helpful)
    },
    [suggestion.id, onFeedback]
  )

  const confidencePercent = Math.round(suggestion.confidence * 100)
  const priorityClass = priorityColors[suggestion.priority] ?? 'text-slate-400'

  return (
    <div
      data-testid="ai-suggestion-card"
      className="relative rounded-xl border-2 border-violet-400/40 bg-slate-950/80 p-4 shadow-lg backdrop-blur"
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg" aria-hidden="true">
            🤖
          </span>
          <h4 className="text-sm font-semibold text-violet-200">
            AI Coaching Insight
          </h4>
          {suggestion.topic && (
            <span className="rounded-full border border-violet-400/20 bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-300">
              {suggestion.topic}
            </span>
          )}
        </div>
        <button
          type="button"
          data-testid="dismiss-suggestion-btn"
          onClick={onDismiss}
          className="ml-2 rounded-md p-1 text-slate-500 transition-colors hover:bg-white/5 hover:text-slate-300"
          aria-label="Dismiss suggestion"
        >
          ✕
        </button>
      </div>

      {/* Observation */}
      <div className="mt-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          Observation
        </p>
        <p data-testid="observation-text" className="mt-0.5 text-sm text-slate-300">
          {suggestion.observation}
        </p>
      </div>

      {/* Suggestion */}
      <div className="mt-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          Suggestion
        </p>
        <p data-testid="suggestion-text" className="mt-0.5 text-sm text-slate-200">
          {suggestion.suggestion}
        </p>
      </div>

      {/* Suggested Prompt */}
      {suggestion.suggested_prompt && (
        <SuggestedPromptBlock
          prompt={suggestion.suggested_prompt}
          onUse={onUsePrompt}
        />
      )}

      {/* Footer: confidence bar + priority + feedback */}
      <div className="mt-3 flex items-center justify-between">
        {/* Confidence bar */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium text-slate-500">
            Confidence
          </span>
          <div className="h-1.5 w-20 rounded-full bg-slate-800">
            <div
              data-testid="confidence-bar-fill"
              className="h-1.5 rounded-full bg-violet-400 transition-all"
              style={{ width: `${confidencePercent}%` }}
            />
          </div>
          <span
            data-testid="confidence-value"
            className="text-[10px] tabular-nums text-slate-400"
          >
            {confidencePercent}%
          </span>
          <span className={`ml-2 text-[10px] font-medium ${priorityClass}`}>
            {suggestion.priority}
          </span>
        </div>

        {/* Feedback buttons */}
        <div className="flex items-center gap-1">
          {feedbackGiven === null ? (
            <>
              <button
                type="button"
                data-testid="feedback-helpful-btn"
                onClick={() => handleFeedback(true)}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs transition-colors hover:bg-emerald-500/20 hover:text-emerald-300"
                aria-label="Helpful"
              >
                👍
              </button>
              <button
                type="button"
                data-testid="feedback-unhelpful-btn"
                onClick={() => handleFeedback(false)}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs transition-colors hover:bg-red-500/20 hover:text-red-300"
                aria-label="Not helpful"
              >
                👎
              </button>
            </>
          ) : (
            <span
              data-testid="feedback-thanks"
              className="text-[11px] text-slate-500"
            >
              {feedbackGiven ? '👍 Thanks!' : '👎 Noted'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
