import { useEffect, useRef, useCallback } from 'react'

interface ProgressMessage {
  type: 'task:progress'
  task_id: string
  progress: number
  status: string
}

type MessageHandler = (msg: ProgressMessage) => void

export function useWebSocket(taskId: string | null, onMessage: MessageHandler) {
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!taskId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/${taskId}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ProgressMessage
        onMessage(msg)
      } catch { /* ignore parse errors */ }
    }

    ws.onerror = () => console.warn(`WebSocket error for task: ${taskId}`)
    ws.onclose = () => { wsRef.current = null }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [taskId, onMessage])

  const close = useCallback(() => {
    wsRef.current?.close()
  }, [])

  return { close }
}
