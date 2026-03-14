'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { UserRole } from '@/lib/auth-types'
import type { TranscriptMessage as TranscriptMessageData } from '@/lib/types'
import { TranscriptMessage } from './TranscriptMessage'

interface TranscriptPanelProps {
  /** Ordered list of transcript messages (sorted by start_time ascending). */
  messages: TranscriptMessageData[]
  /** Whether the panel is initially collapsed. Defaults to false. */
  defaultCollapsed?: boolean
  /** Tutor-only guard. Student and guest views render nothing. */
  viewerRole?: UserRole
}

/**
 * Collapsible sidebar panel that displays a live transcript feed.
 *
 * Features:
 * - Auto-scrolls to bottom as new messages arrive.
 * - Keeps the latest partial transcript in view while it updates in place.
 * - When the user scrolls up, a "↓ Scroll to bottom" button appears.
 * - Compact layout using Tailwind, following the existing dark-mode styling.
 * - Tutor-only: never rendered in student/guest views.
 */
export function TranscriptPanel({
  messages,
  defaultCollapsed = false,
  viewerRole = 'tutor',
}: TranscriptPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const prevMessageCountRef = useRef(0)
  const prevTailSignatureRef = useRef('')

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
      setIsAtBottom(true)
    }
  }, [])

  const tailSignature = useMemo(() => {
    const last = messages[messages.length - 1]
    if (!last) return ''
    return [last.utterance_id, last.revision, last.text, last.is_partial].join(':')
  }, [messages])

  // Detect whether the user has scrolled away from the bottom.
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const threshold = 40 // px tolerance
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
    setIsAtBottom(atBottom)
  }, [])

  // Auto-scroll when new messages arrive or the latest partial updates in place,
  // but only while the viewer is already following the bottom.
  useEffect(() => {
    const countIncreased = messages.length > prevMessageCountRef.current
    const tailChanged = tailSignature !== prevTailSignatureRef.current

    if ((countIncreased || tailChanged) && isAtBottom) {
      scrollToBottom()
    }

    prevMessageCountRef.current = messages.length
    prevTailSignatureRef.current = tailSignature
  }, [messages.length, tailSignature, isAtBottom, scrollToBottom])

  if (viewerRole !== 'tutor') {
    return null
  }

  return (
    <div
      data-testid="transcript-panel"
      className="flex h-full flex-col rounded-2xl border border-white/10 bg-slate-950/75 backdrop-blur"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
        <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
          Transcript
        </h3>
        <button
          data-testid="transcript-toggle"
          onClick={() => setCollapsed((c) => !c)}
          className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-medium text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-200"
          aria-label={collapsed ? 'Show transcript' : 'Hide transcript'}
        >
          {collapsed ? 'Show' : 'Hide'}
        </button>
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="relative flex-1">
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="h-full min-h-[120px] overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-white/10"
          >
            {messages.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-xs text-slate-500">
                Waiting for speech…
              </div>
            ) : (
              <div className="py-1">
                {messages.map((msg) => (
                  <TranscriptMessage key={msg.utterance_id} message={msg} />
                ))}
              </div>
            )}
          </div>

          {/* Scroll-to-bottom button */}
          {!isAtBottom && messages.length > 0 && (
            <button
              data-testid="scroll-to-bottom"
              onClick={scrollToBottom}
              className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-white/15 bg-slate-900/90 px-3 py-1 text-[11px] font-medium text-slate-300 shadow-lg backdrop-blur transition-colors hover:bg-slate-800/90 hover:text-white"
            >
              ↓ Scroll to bottom
            </button>
          )}
        </div>
      )}
    </div>
  )
}
