'use client'

import { useCallback, useState } from 'react'
import type { AISuggestion } from '@/lib/types'
import { SuggestedPromptBlock } from './SuggestedPromptBlock'

interface AISuggestionCardProps {
  suggestion?: AISuggestion | null
  /** True while the suggestion request is in flight. */
  loading?: boolean
  onDismiss?: () => void
  onFeedback?: (suggestionId: string, helpful: boolean) => void
  onUsePrompt?: (prompt: string) => void
}

const priorityColors: Record<string, string> = {
  high: 'text-red-300',
  medium: 'text-amber-300',
  low: 'text-slate-400',
}

export function AISuggestionCard({
  suggestion,
  loading,
  onDismiss,
  onFeedback,
  onUsePrompt,
}: AISuggestionCardProps) {
  const [feedbackGiven, setFeedbackGiven] = useState<boolean | null>(null)

  const handleFeedback = useCallback(
    (helpful: boolean) => {
      setFeedbackGiven(helpful)
      if (suggestion) onFeedback?.(suggestion.id, helpful)
    },
    [suggestion, onFeedback]
  )

  // Loading state — compact indicator while waiting for LLM
  if (loading && !suggestion) {
    return (
      <div
        data-testid="ai-suggestion-card"
        className="relative rounded-xl border border-violet-400/30 bg-slate-950/80 px-4 py-3 shadow-lg backdrop-blur"
      >
        <div className="flex items-center gap-2">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-400/30 border-t-violet-400" />
          <span className="text-xs text-violet-200/70">Generating insight...</span>
        </div>
      </div>
    )
  }

  // Nothing to show
  if (!suggestion) return null

  const confidencePercent = Math.round(suggestion.confidence * 100)
  const priorityClass = priorityColors[suggestion.priority] ?? 'text-slate-400'

  return (
    <div
      data-testid="ai-suggestion-card"
      className="relative rounded-xl border border-violet-400/30 bg-slate-950/80 p-4 shadow-lg backdrop-blur"
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-violet-500/20">
            <svg className="h-3 w-3 text-violet-300" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 1a2.5 2.5 0 0 0-2.5 2.5c0 .86.43 1.62 1.1 2.07A4.5 4.5 0 0 0 3.5 10v1a.5.5 0 0 0 .5.5h2v2a.5.5 0 0 0 .5.5h3a.5.5 0 0 0 .5-.5v-2h2a.5.5 0 0 0 .5-.5v-1a4.5 4.5 0 0 0-3.1-4.43A2.5 2.5 0 0 0 10.5 3.5 2.5 2.5 0 0 0 8 1z"/>
            </svg>
          </div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-violet-200/80">
            AI Insight
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
          aria-label="Dismiss"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/></svg>
        </button>
      </div>

      {/* Observation */}
      <p data-testid="observation-text" className="mt-2.5 text-sm leading-snug text-slate-300">
        {suggestion.observation}
      </p>

      {/* Suggestion */}
      <p data-testid="suggestion-text" className="mt-1.5 text-sm leading-snug text-slate-100">
        {suggestion.suggestion}
      </p>

      {/* Suggested Prompt */}
      {suggestion.suggested_prompt && (
        <SuggestedPromptBlock
          prompt={suggestion.suggested_prompt}
          onUse={onUsePrompt}
        />
      )}

      {/* Footer */}
      <div className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-1 w-16 rounded-full bg-slate-800">
            <div
              data-testid="confidence-bar-fill"
              className="h-1 rounded-full bg-violet-400/70 transition-all"
              style={{ width: `${confidencePercent}%` }}
            />
          </div>
          <span
            data-testid="confidence-value"
            className="text-[10px] tabular-nums text-slate-500"
          >
            {confidencePercent}%
          </span>
          <span className={`text-[10px] font-medium ${priorityClass}`}>
            {suggestion.priority}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {feedbackGiven === null ? (
            <>
              <button
                type="button"
                data-testid="feedback-helpful-btn"
                onClick={() => handleFeedback(true)}
                className="rounded-md border border-white/10 bg-white/5 p-1.5 text-slate-400 transition-colors hover:bg-emerald-500/20 hover:text-emerald-300"
                aria-label="Helpful"
              >
                <svg className="h-3 w-3" viewBox="0 0 16 16" fill="currentColor"><path d="M6.956 1.745C7.021.81 7.908.087 8.864.325l.261.066c.463.116.874.456 1.012.965.22.816.533 2.511.062 4.51a10 10 0 0 1 .443-.051c.713-.065 1.669-.072 2.516.21.518.173.994.681 1.2 1.273.184.532.16 1.162-.234 1.733q.086.18.138.363c.077.27.113.567.113.856s-.036.586-.113.856c-.039.135-.09.273-.16.404.169.387.107.819-.003 1.148a3.2 3.2 0 0 1-.488.901c.054.152.076.312.076.465 0 .305-.089.625-.253.912C13.1 15.522 12.437 16 11.5 16H8c-.605 0-1.07-.081-1.466-.218a4.8 4.8 0 0 1-.97-.484l-.048-.03c-.504-.307-.999-.609-2.068-.722C2.682 14.464 2 13.846 2 13V9c0-.85.685-1.432 1.357-1.615.849-.232 1.574-.787 2.132-1.41.56-.627.914-1.28 1.039-1.639.199-.575.356-1.539.428-2.59z"/></svg>
              </button>
              <button
                type="button"
                data-testid="feedback-unhelpful-btn"
                onClick={() => handleFeedback(false)}
                className="rounded-md border border-white/10 bg-white/5 p-1.5 text-slate-400 transition-colors hover:bg-red-500/20 hover:text-red-300"
                aria-label="Not helpful"
              >
                <svg className="h-3 w-3" viewBox="0 0 16 16" fill="currentColor"><path d="M6.956 14.534c.065.936.952 1.659 1.908 1.42l.261-.065a1.38 1.38 0 0 0 1.012-.965c.22-.816.533-2.512.062-4.51q.205.03.443.051c.713.065 1.669.071 2.516-.211.518-.173.994-.68 1.2-1.272a1.9 1.9 0 0 0-.234-1.734c.058-.118.103-.242.138-.362.077-.27.113-.568.113-.856 0-.29-.036-.586-.113-.857a2 2 0 0 0-.16-.403c.169-.387.107-.82-.003-1.149a3.2 3.2 0 0 0-.488-.9c.054-.153.076-.313.076-.466 0-.305-.089-.625-.253-.912C13.1.757 12.437.28 11.5.28H8c-.605 0-1.07.08-1.466.217a4.8 4.8 0 0 0-.97.485l-.048.029c-.504.308-.999.61-2.068.723C2.682 1.815 2 2.434 2 3.279v4c0 .851.685 1.433 1.357 1.616.849.232 1.574.787 2.132 1.41.56.626.914 1.28 1.039 1.638.199.576.356 1.54.428 2.591"/></svg>
              </button>
            </>
          ) : (
            <span
              data-testid="feedback-thanks"
              className="text-[10px] text-slate-500"
            >
              {feedbackGiven ? 'Thanks!' : 'Noted'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
