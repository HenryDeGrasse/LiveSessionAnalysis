'use client'

import { useCallback, useState } from 'react'

interface SuggestedPromptBlockProps {
  prompt: string
  onUse?: (prompt: string) => void
}

export function SuggestedPromptBlock({ prompt, onUse }: SuggestedPromptBlockProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may not be available
    }
  }, [prompt])

  const handleUse = useCallback(() => {
    onUse?.(prompt)
  }, [onUse, prompt])

  return (
    <div
      data-testid="suggested-prompt-block"
      className="mt-2 rounded-lg border border-violet-400/15 bg-violet-500/5 px-3 py-2"
    >
      <p
        data-testid="suggested-prompt-text"
        className="text-sm italic leading-snug text-violet-100/90"
      >
        &ldquo;{prompt}&rdquo;
      </p>
      <div className="mt-1.5 flex gap-2">
        <button
          type="button"
          data-testid="copy-prompt-btn"
          onClick={handleCopy}
          className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] font-medium text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        {onUse && (
          <button
            type="button"
            data-testid="use-prompt-btn"
            onClick={handleUse}
            className="rounded-md border border-violet-400/30 bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium text-violet-200 transition-colors hover:bg-violet-500/25 hover:text-white"
          >
            Use
          </button>
        )}
      </div>
    </div>
  )
}
