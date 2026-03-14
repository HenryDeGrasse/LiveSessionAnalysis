'use client'

import { useCallback, useState } from 'react'

interface SuggestedPromptBlockProps {
  /** The suggested prompt text to display. */
  prompt: string
  /** Called when the tutor clicks "Use" — typically inserts the prompt into a chat input. */
  onUse?: (prompt: string) => void
}

/**
 * Highlighted block for a suggested tutor prompt with copy-to-clipboard
 * and optional "Use" functionality.
 */
export function SuggestedPromptBlock({ prompt, onUse }: SuggestedPromptBlockProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may not be available in all contexts
    }
  }, [prompt])

  const handleUse = useCallback(() => {
    onUse?.(prompt)
  }, [onUse, prompt])

  return (
    <div
      data-testid="suggested-prompt-block"
      className="mt-2 rounded-lg border border-violet-400/20 bg-violet-500/10 px-3 py-2"
    >
      <p className="text-[11px] font-semibold uppercase tracking-wider text-violet-300/70">
        Suggested Prompt
      </p>
      <p
        data-testid="suggested-prompt-text"
        className="mt-1 text-sm italic text-violet-100"
      >
        &ldquo;{prompt}&rdquo;
      </p>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          data-testid="copy-prompt-btn"
          onClick={handleCopy}
          className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          {copied ? '✓ Copied' : '📋 Copy'}
        </button>
        {onUse && (
          <button
            type="button"
            data-testid="use-prompt-btn"
            onClick={handleUse}
            className="rounded-md border border-violet-400/30 bg-violet-500/20 px-2.5 py-1 text-[11px] font-medium text-violet-200 transition-colors hover:bg-violet-500/30 hover:text-white"
          >
            ▶ Use
          </button>
        )}
      </div>
    </div>
  )
}
