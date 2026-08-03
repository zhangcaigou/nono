 import { useState, useEffect, useRef, useCallback } from 'react'
import { getTask, getTaskResult, cancelTask } from '@/api/search'
import { SearchTask, SearchResult, TaskStatus } from '@/types'
import { AxiosError } from 'axios'

interface UseTaskPollingReturn {
  task: SearchTask | null
  result: SearchResult | null
  isLoading: boolean
  error: string | null
  refetch: () => void
  cancel: () => Promise<void>
}

export function useTaskPolling(taskId: string | undefined): UseTaskPollingReturn {
  const [task, setTask] = useState<SearchTask | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const timerRef = useRef<number | null>(null)
  const isMountedRef = useRef(true)
  const isPollingRef = useRef(false) // 防止重叠请求

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // 获取任务和结果的逻辑
  const fetchData = useCallback(
    async (isRetry = false) => {
      if (!taskId || !isMountedRef.current) return
      if (isPollingRef.current) return
      isPollingRef.current = true

      try {
        const taskData = await getTask(taskId)
        if (!isMountedRef.current) return
        setTask(taskData)
        setError(null)

        // 终态：停止轮询，并获取结果
        const terminalStates: TaskStatus[] = ['succeeded', 'failed', 'cancelled']
        if (terminalStates.includes(taskData.status)) {
          stopPolling()
          if (taskData.status === 'succeeded') {
            try {
              const resultData = await getTaskResult(taskId)
              if (isMountedRef.current) setResult(resultData)
            } catch (resErr) {
              // 如果结果获取失败，但任务已经是 succeeded，这里记录错误但不覆盖主错误
              if (isMountedRef.current) {
                setError('获取结果失败，请稍后重试')
              }
            }
          }
        } else {
          // 非终态：确保轮询开启
          if (!timerRef.current) {
            const interval = window.setInterval(() => {
              fetchData(false)
            }, 2000) // 2秒间隔
            timerRef.current = interval
          }
        }
      } catch (err) {
        if (!isMountedRef.current) return
        const axiosErr = err as AxiosError<any>
        // 如果是 404，停止轮询，提示任务不存在
        if (axiosErr.response?.status === 404) {
          stopPolling()
          setError('任务不存在或已失效')
          setTask(null)
        } else if (axiosErr.response?.status === 409) {
          // 可能是任务未完成，继续轮询（不要报错）
          // 但这里如果是获取结果时的 409，我们不需要管，fetchData只处理getTask
        } else {
          // 网络错误等，进行指数退避
          setError('网络异常，正在重试...')
          // 如果已经失败，不要无限重试，但保留轮询
        }
      } finally {
        isPollingRef.current = false
        if (isMountedRef.current) setIsLoading(false)
      }
    },
    [taskId, stopPolling]
  )

  // 手动 refetch
  const refetch = useCallback(() => {
    stopPolling()
    setIsLoading(true)
    setError(null)
    fetchData(false)
  }, [fetchData, stopPolling])

  // 取消任务
  const cancel = useCallback(async () => {
    if (!taskId) return
    try {
      await cancelTask(taskId)
      // 取消后立即轮询一次获取最新状态（cancelled）
      await fetchData(false)
    } catch (err) {
      const axiosErr = err as AxiosError<any>
      if (axiosErr.response?.status === 409) {
        setError('任务已结束或无法取消')
      } else {
        setError('取消失败，请稍后重试')
      }
    }
  }, [taskId, fetchData])

  // 初始化与清理
  useEffect(() => {
    isMountedRef.current = true
    if (taskId) {
      fetchData(false)
    } else {
      setIsLoading(false)
    }

    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, [taskId, fetchData, stopPolling])

  // 页面可见性变化：切到后台时降低频率（简单实现：切换时重启间隔）
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // 切到后台，可以加大间隔，但我们保持原样，由浏览器控制最小间隔
        // 或者简单停止，这里我们不停，因为浏览器会限制定时器
      } else {
        // 回到前台立即刷一次
        if (task && !['succeeded', 'failed', 'cancelled'].includes(task.status)) {
          fetchData(false)
        }
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [fetchData, task])

  return { task, result, isLoading, error, refetch, cancel }
}