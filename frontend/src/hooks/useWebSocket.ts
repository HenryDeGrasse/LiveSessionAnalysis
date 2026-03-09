'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { WS_URL } from '@/lib/constants'
import type { WSMessage } from '@/lib/types'

interface UseWebSocketOptions {
  sessionId: string
  token: string
  onMessage?: (message: WSMessage) => void
  onOpen?: () => void
  onClose?: () => void
}

export function useWebSocket({
  sessionId,
  token,
  onMessage,
  onOpen,
  onClose,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)

  const connect = useCallback(() => {
    if (!sessionId || !token) return
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    const url = `${WS_URL}/ws/session/${sessionId}?token=${token}`
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      reconnectAttemptsRef.current = 0
      onOpen?.()
    }

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const message = JSON.parse(event.data) as WSMessage
          onMessage?.(message)
        } catch {
          console.error('Failed to parse WS message')
        }
      }
    }

    ws.onclose = (event) => {
      setConnected(false)
      onClose?.()

      // Reconnect with exponential backoff (unless intentional or terminal close)
      const terminalCodes = [4001, 4003, 4004, 1000] // invalid token, session ended, not found, normal close
      if (!terminalCodes.includes(event.code)) {
        const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 10000)
        reconnectAttemptsRef.current++
        reconnectTimeoutRef.current = setTimeout(connect, delay)
      } else if (event.code === 4001 || event.code === 4004) {
        setError(event.reason || 'Connection rejected')
      } else if (event.code === 4003) {
        setError('Session has already ended')
      }
    }

    ws.onerror = () => {
      setError('WebSocket error')
    }
  }, [sessionId, token, onMessage, onOpen, onClose])

  useEffect(() => {
    if (!sessionId || !token) {
      setConnected(false)
      return
    }

    connect()
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close(1000)
    }
  }, [sessionId, token, connect])

  const sendBinary = useCallback((data: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data)
    }
  }, [])

  const sendJson = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { connected, error, sendBinary, sendJson }
}
