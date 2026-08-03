import { useParams, useNavigate } from 'react-router-dom'
import { useState, useRef, useEffect, useCallback } from 'react'
import {
  SearchTask,
  SearchResult,
  RecommendationTrace,
  ConstraintAssessment,
  ConstraintStatus,
  Evidence,
  RecommendationReason,
  PaperRelation,
  RelationType,
  PaperItem,
} from '@/types'
import {
  getTask,
  getTaskResult,
  cancelTask,
  createSearchTask,
  getPaperTrace,
} from '@/api/search'
import { stageToChinese, formatTime, calcDuration, scoreToPercent } from '@/utils/format'
import ChatInput from '@/components/ChatInput'

// ===== 对话数据结构 =====
interface ConversationEntry {
  taskId: string
  query: string
  task: SearchTask | null
  result: SearchResult | null
  isLoading: boolean
  error: string | null
}

// ===== localStorage 对话持久化 =====
function getConvKey(rootTaskId: string) {
  return `nono_conv_${rootTaskId}`
}

function saveConversation(rootTaskId: string, entries: { taskId: string; query: string }[]) {
  try {
    localStorage.setItem(getConvKey(rootTaskId), JSON.stringify(entries))
  } catch { /* ignore */ }
}

function loadConversation(rootTaskId: string): { taskId: string; query: string }[] | null {
  try {
    const raw = localStorage.getItem(getConvKey(rootTaskId))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export default function TaskPage() {
  const { taskId: urlTaskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()

  const [conversation, setConversation] = useState<ConversationEntry[]>([])
  const [isPageLoading, setIsPageLoading] = useState(true)
  const [pageError, setPageError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showSelectedOnly, setShowSelectedOnly] = useState(true)
  const [sortBy, setSortBy] = useState<'score' | 'title' | 'year'>('score')
  const [yearFrom, setYearFrom] = useState('')
  const [yearTo, setYearTo] = useState('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const timersRef = useRef<Map<string, number>>(new Map())
  const isMountedRef = useRef(true)
  const isNearBottomRef = useRef(true)
  const prevConvLengthRef = useRef(0)

  // ===== 获取任务数据并按需轮询 =====
  const fetchAndPoll = useCallback(async (taskId: string, index: number) => {
    const doFetch = async (): Promise<boolean> => {
      try {
        const taskData = await getTask(taskId)
        if (!isMountedRef.current) return true

        setConversation((prev) => {
          const updated = [...prev]
          if (updated[index]) {
            updated[index] = {
              ...updated[index],
              task: taskData,
              query: updated[index].query || taskData.query,
              isLoading: false,
            }
          }
          return updated
        })

        const isTerminal = ['succeeded', 'failed', 'cancelled'].includes(taskData.status)

        if (isTerminal) {
          const timer = timersRef.current.get(taskId)
          if (timer) {
            clearInterval(timer)
            timersRef.current.delete(taskId)
          }

          if (taskData.status === 'succeeded') {
            try {
              const resultData = await getTaskResult(taskId)
              if (!isMountedRef.current) return true
              setConversation((prev) => {
                const updated = [...prev]
                if (updated[index]) {
                  updated[index] = { ...updated[index], result: resultData }
                }
                return updated
              })
            } catch { /* ignore */ }
          }
          return true
        }
        return false
      } catch (err: any) {
        if (!isMountedRef.current) return true
        if (err.response?.status === 404) {
          setConversation((prev) => {
            const updated = [...prev]
            if (updated[index]) {
              updated[index] = { ...updated[index], error: '任务不存在或已失效', isLoading: false }
            }
            return updated
          })
          return true
        }
        return false
      }
    }

    const shouldStop = await doFetch()
    if (!shouldStop && isMountedRef.current) {
      const timer = window.setInterval(async () => {
        const stop = await doFetch()
        if (stop) {
          const t = timersRef.current.get(taskId)
          if (t) {
            clearInterval(t)
            timersRef.current.delete(taskId)
          }
        }
      }, 2000)
      timersRef.current.set(taskId, timer)
    }
  }, [])

  // ===== 初始化对话 =====
  useEffect(() => {
    isMountedRef.current = true
    if (!urlTaskId) {
      setIsPageLoading(false)
      setPageError('无效的任务 ID')
      return
    }

    // 尝试恢复已保存的对话
    const saved = loadConversation(urlTaskId)
    if (saved && saved.length > 0) {
      const entries: ConversationEntry[] = saved.map((s) => ({
        taskId: s.taskId,
        query: s.query,
        task: null,
        result: null,
        isLoading: true,
        error: null,
      }))
      setConversation(entries)
      entries.forEach((entry, idx) => void fetchAndPoll(entry.taskId, idx))
    } else {
      // 单任务对话
      setConversation([{
        taskId: urlTaskId,
        query: '',
        task: null,
        result: null,
        isLoading: true,
        error: null,
      }])
      void fetchAndPoll(urlTaskId, 0)
    }

    setIsPageLoading(false)

    return () => {
      isMountedRef.current = false
      timersRef.current.forEach((t) => clearInterval(t))
      timersRef.current.clear()
    }
  }, [urlTaskId, fetchAndPoll])

  // ===== 监听用户滚动位置，判断是否靠近底部 =====
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      // 距离底部 100px 以内视为"靠近底部"
      isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 100
    }

    container.addEventListener('scroll', handleScroll, { passive: true })
    return () => container.removeEventListener('scroll', handleScroll)
  }, [isPageLoading])

  // ===== 测量聊天容器实际宽度（不含滚动条），供结果面板精确占满全宽，避免水平滚动条 =====
  const [chatWidth, setChatWidth] = useState<number | null>(null)

  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    const update = () => setChatWidth(container.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(container)
    return () => ro.disconnect()
  }, [isPageLoading])

  // ===== 智能自动滚动：仅在用户靠近底部或有新消息时滚动 =====
  useEffect(() => {
    const isNewMessage = conversation.length > prevConvLengthRef.current
    prevConvLengthRef.current = conversation.length

    if (isNewMessage || isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [conversation])

  // ===== 追问：在当前对话中追加 =====
  const handleFollowUp = async (query: string, opts?: any) => {
    if (isSubmitting || !urlTaskId) return
    setIsSubmitting(true)

    try {
      const accepted = await createSearchTask({
        query,
        end_date: opts?.end_date || null,
        options: opts?.options,
      })

      const newEntry: ConversationEntry = {
        taskId: accepted.task_id,
        query,
        task: null,
        result: null,
        isLoading: true,
        error: null,
      }

      setConversation((prev) => {
        const updated = [...prev, newEntry]
        saveConversation(urlTaskId, updated.map((e) => ({ taskId: e.taskId, query: e.query })))
        return updated
      })

      // 轮询新任务（index 是当前 conversation.length，因为刚 push 了一个）
      void fetchAndPoll(accepted.task_id, conversation.length)
    } catch { /* ignore */ } finally {
      setIsSubmitting(false)
    }
  }

  // ===== 取消任务 =====
  const handleCancel = async (taskId: string, index: number) => {
    try {
      await cancelTask(taskId)
      const taskData = await getTask(taskId)
      setConversation((prev) => {
        const updated = [...prev]
        if (updated[index]) {
          updated[index] = { ...updated[index], task: taskData }
        }
        return updated
      })
    } catch { /* ignore */ }
  }

  // ===== 重试失败任务 =====
  const handleRetry = (index: number) => {
    const entry = conversation[index]
    if (!entry) return
    setConversation((prev) => {
      const updated = [...prev]
      updated[index] = { ...updated[index], isLoading: true, error: null }
      return updated
    })
    void fetchAndPoll(entry.taskId, index)
  }

  // ===== Loading =====
  if (isPageLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full border-[3px] border-gray-200 border-t-indigo-600 animate-spin" />
          <p className="text-gray-400 text-sm">加载任务中...</p>
        </div>
      </div>
    )
  }

  // ===== 页面级错误 =====
  if (pageError) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center max-w-md animate-scale-in">
          <div className="w-16 h-16 rounded-2xl bg-red-50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">任务不存在</h2>
          <p className="text-gray-500 text-sm mb-6">{pageError}</p>
          <button
            onClick={() => navigate('/')}
            className="px-6 py-2.5 bg-indigo-600 text-white rounded-xl font-medium shadow-md shadow-indigo-200 hover:bg-indigo-700 transition-all duration-200"
          >
            返回首页
          </button>
        </div>
      </div>
    )
  }

  // ===== 检查是否全部 404 =====
  const allErrors = conversation.length > 0 && conversation.every((e) => e.error)
  if (allErrors) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center max-w-md animate-scale-in">
          <div className="w-16 h-16 rounded-2xl bg-red-50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">任务不存在</h2>
          <p className="text-gray-500 text-sm mb-6">{conversation[0]?.error || '任务不存在或已失效'}</p>
          <button
            onClick={() => navigate('/')}
            className="px-6 py-2.5 bg-indigo-600 text-white rounded-xl font-medium shadow-md shadow-indigo-200 hover:bg-indigo-700 transition-all duration-200"
          >
            返回首页
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 聊天消息区域 */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto overflow-x-hidden">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">

          {conversation.map((entry, idx) => (
            <ConversationMessage
              key={entry.taskId}
              entry={entry}
              index={idx}
              onCancel={handleCancel}
              onRetry={handleRetry}
              showSelectedOnly={showSelectedOnly}
              sortBy={sortBy}
              yearFrom={yearFrom}
              yearTo={yearTo}
              chatWidth={chatWidth}
              onToggleFilter={() => setShowSelectedOnly(!showSelectedOnly)}
              onSortChange={setSortBy}
              onYearFromChange={setYearFrom}
              onYearToChange={setYearTo}
            />
          ))}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* 底部输入 */}
      <div className="border-t border-gray-100 bg-white/80 backdrop-blur-sm px-4 py-3">
        <div className="max-w-3xl mx-auto">
          <ChatInput
            onSubmit={handleFollowUp}
            isSubmitting={isSubmitting}
            placeholder="继续提问..."
            showAdvanced
          />
        </div>
      </div>
    </div>
  )
}

// ===== 单条对话消息（用户提问 + AI 回复） =====
function ConversationMessage({
  entry,
  index,
  onCancel,
  onRetry,
  showSelectedOnly,
  sortBy,
  yearFrom,
  yearTo,
  chatWidth,
  onToggleFilter,
  onSortChange,
  onYearFromChange,
  onYearToChange,
}: {
  entry: ConversationEntry
  index: number
  onCancel: (taskId: string, index: number) => void
  onRetry: (index: number) => void
  showSelectedOnly: boolean
  sortBy: 'score' | 'title' | 'year'
  yearFrom: string
  yearTo: string
  chatWidth: number | null
  onToggleFilter: () => void
  onSortChange: (val: 'score' | 'title' | 'year') => void
  onYearFromChange: (val: string) => void
  onYearToChange: (val: string) => void
}) {
  const { task, result, isLoading, error } = entry

  // 加载中
  if (isLoading && !task) {
    return (
      <div className="space-y-6 animate-fade-in">
        {/* 用户消息 */}
        <UserMessage query={entry.query || '加载中...'} />
        {/* AI 加载中 */}
        <div className="flex gap-4">
          <AssistantAvatar />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 mb-1">NoNo</p>
            <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md p-5 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <svg className="animate-spin w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                加载任务中...
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // 任务不存在
  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <UserMessage query={entry.query} />
        <div className="flex gap-4">
          <AssistantAvatar />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 mb-1">NoNo</p>
            <div className="bg-red-50 border border-red-100 rounded-2xl rounded-tl-md p-5">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!task) return null

  const isTerminal = ['succeeded', 'failed', 'cancelled'].includes(task.status)
  const isCancelled = task.status === 'cancelled'
  const isSucceeded = task.status === 'succeeded'

  // 阶段步骤（用于步骤指示器）— 平滑过渡，让快速阶段也有视觉停留
  const stageSteps: { key: string; label: string }[] = [
    { key: 'queued', label: '排队' },
    { key: 'loading', label: '加载' },
    { key: 'searching', label: '搜索' },
    { key: 'enriching', label: '补全' },
    { key: 'finished', label: '完成' },
  ]
  const actualStepIdx = stageSteps.findIndex((s) => s.key === task.stage)

  // 平滑阶段过渡：让前几个快速阶段至少有视觉停留
  const [displayedStepIdx, setDisplayedStepIdx] = useState(0)
  const stageTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (actualStepIdx < 0) return
    if (actualStepIdx <= displayedStepIdx) {
      // 终态直接跳转
      const isTerminalStatus = task.status === 'succeeded' || task.status === 'failed' || task.status === 'cancelled'
      if (isTerminalStatus) setDisplayedStepIdx(actualStepIdx)
      return
    }

    // 逐步推进，每步间隔 5 秒：前面的快速阶段（排队/加载）在视觉上充分停留，避免搜索阶段显得过短
    if (stageTimerRef.current) clearTimeout(stageTimerRef.current)
    stageTimerRef.current = window.setTimeout(() => {
      setDisplayedStepIdx((prev) => Math.min(prev + 1, actualStepIdx))
    }, 5000)

    return () => {
      if (stageTimerRef.current) clearTimeout(stageTimerRef.current)
    }
  }, [actualStepIdx, displayedStepIdx, task.status])

  const currentStepIdx = isTerminal ? stageSteps.length - 1 : displayedStepIdx

  // 筛选论文：入选 + 年份范围
  const filteredPapers = result
    ? result.papers.filter((p) => {
        if (showSelectedOnly && !p.selected) return false
        // 年份筛选：null 年份的论文保留
        if (yearFrom && p.publication_year != null && p.publication_year < Number(yearFrom)) return false
        if (yearTo && p.publication_year != null && p.publication_year > Number(yearTo)) return false
        return true
      })
    : []
  const sortedPapers = [...filteredPapers].sort((a, b) => {
    if (sortBy === 'score') return b.score - a.score
    if (sortBy === 'year') {
      // null 年份排在最后
      const ya = a.publication_year ?? -1
      const yb = b.publication_year ?? -1
      return yb - ya
    }
    return (a.title || '').localeCompare(b.title || '')
  })

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 用户消息 */}
      <UserMessage query={entry.query || task.query} timestamp={task.created_at} />

      {/* AI 回复 */}
      <div className="flex gap-4">
        <AssistantAvatar />
        <div className="flex-1 min-w-0 space-y-4">
          {/* 选中论文后，结果面板将跳出居中列占满全宽，此处用占位保持布局稳定 */}
          <p className={`text-sm font-semibold text-gray-800 mb-1 ${isSucceeded && result && sortedPapers.length > 0 ? 'invisible' : ''}`}>NoNo</p>

          {/* 状态 + 操作 */}
          <div className="flex items-center gap-3">
            <StatusBadge status={task.status} />
            {!isTerminal && (
              <button
                onClick={() => onCancel(entry.taskId, index)}
                className="text-xs text-red-500 hover:text-red-700 font-medium transition-colors"
              >
                取消任务
              </button>
            )}
            <span className="text-xs text-gray-400 ml-auto font-mono">
              {task.task_id.slice(0, 8)}...
            </span>
          </div>

          {/* 进度区域 */}
          {!isTerminal && (
            <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md p-5 shadow-sm space-y-5">
              {/* 阶段步骤指示器 */}
              <div className="flex items-center gap-0">
                {stageSteps.map((step, i) => {
                  const isActive = i === currentStepIdx
                  const isDone = i < currentStepIdx
                  return (
                    <div key={step.key} className="flex items-center flex-1 last:flex-none">
                      <div className="flex flex-col items-center">
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                          isDone
                            ? 'bg-indigo-600 text-white'
                            : isActive
                            ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200 scale-110'
                            : 'bg-gray-100 text-gray-400 border border-gray-200'
                        }`}>
                          {isDone ? (
                            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                          ) : isActive ? (
                            <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          ) : (
                            i + 1
                          )}
                        </div>
                        <span className={`text-[10px] mt-1 font-medium transition-colors ${
                          isDone || isActive ? 'text-indigo-600' : 'text-gray-400'
                        }`}>
                          {step.label}
                        </span>
                      </div>
                      {i < stageSteps.length - 1 && (
                        <div className={`flex-1 h-0.5 mx-2 mt-[-14px] rounded-full transition-colors duration-500 ${
                          i < currentStepIdx ? 'bg-indigo-600' : 'bg-gray-200'
                        }`} />
                      )}
                    </div>
                  )
                })}
              </div>

              {/* 不确定进度动画条 */}
              <div className="relative">
                <div className="flex items-center gap-2 mb-2">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500" />
                  </span>
                  <span className="text-sm font-medium text-gray-700">{stageToChinese(task.stage)}</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                  <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 animate-indeterminate" />
                </div>
              </div>

              {/* 实时统计 */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <StatCard label="已发现论文" value={task.progress.papers_found} color="indigo" />
                <StatCard label="已选中论文" value={task.progress.papers_selected} color="purple" />
                <StatCard label="扩展层" value={`${task.progress.current_layer}/${task.progress.total_layers}`} color="blue" />
                <DurationStat startedAt={task.started_at} createdAt={task.created_at} finishedAt={task.finished_at} />
              </div>
            </div>
          )}

          {/* 失败 */}
          {task.status === 'failed' && task.error && (
            <div className="bg-red-50 border border-red-100 rounded-2xl rounded-tl-md p-5 space-y-3">
              <div className="flex items-center gap-2">
                <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="font-semibold text-red-800 text-sm">任务执行失败</span>
              </div>
              <p className="text-xs font-mono text-red-600 bg-red-100 inline-block px-2 py-0.5 rounded">{task.error.code}</p>
              <p className="text-sm text-red-700">{task.error.message}</p>
              {task.error.details != null && (
                <pre className="text-xs bg-red-100/80 p-3 rounded-lg overflow-auto max-h-32 font-mono text-red-800 border border-red-200/50">
                  {JSON.stringify(task.error.details, null, 2)}
                </pre>
              )}
              <button
                onClick={() => onRetry(index)}
                className="px-4 py-1.5 bg-red-600 text-white rounded-lg text-xs font-medium hover:bg-red-700 transition-colors"
              >
                重试
              </button>
            </div>
          )}

          {/* 已取消 */}
          {isCancelled && (
            <div className="bg-amber-50 border border-amber-100 rounded-2xl rounded-tl-md p-5 text-sm text-amber-700 flex items-center gap-2">
              <svg className="w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              任务已被取消
            </div>
          )}

          {/* 成功 + 结果 */}
          {isSucceeded && result && (
            <div className="space-y-4">
              <div className="bg-emerald-50 border border-emerald-100 rounded-2xl rounded-tl-md px-5 py-4">
                <div className="flex items-center gap-2 mb-2">
                  <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="font-semibold text-emerald-800 text-sm">搜索完成</span>
                </div>
                <p className="text-sm text-emerald-700">
                  共发现 <strong>{result.papers.length}</strong> 篇论文，其中 <strong>{result.papers.filter((p) => p.selected).length}</strong> 篇被 AI 选中
                </p>
                {result.summary && (
                  <div className="flex flex-wrap gap-3 mt-2 text-xs text-emerald-600">
                    {result.summary.abstract_enriched_count > 0 && (
                      <span>摘要补全 {result.summary.abstract_enriched_count} 篇</span>
                    )}
                    {result.summary.traceable_selected_count > 0 && (
                      <span>可溯源 {result.summary.traceable_selected_count} 篇</span>
                    )}
                    {result.summary.relation_count > 0 && (
                      <span>关系 {result.summary.relation_count} 条</span>
                    )}
                  </div>
                )}
              </div>

              {/* 工具栏 */}
              <div className="flex flex-wrap items-center justify-between gap-3 px-1">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <div className="relative">
                      <input type="checkbox" checked={showSelectedOnly} onChange={onToggleFilter} className="sr-only peer" />
                      <div className="w-8 h-4.5 bg-gray-200 rounded-full peer-checked:bg-emerald-500 transition-colors" />
                      <div className="absolute top-0.5 left-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm peer-checked:translate-x-3.5 transition-transform" />
                    </div>
                    <span className="text-xs text-gray-500">只看入选</span>
                  </label>

                  {/* 年份筛选 */}
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      placeholder="起始年"
                      value={yearFrom}
                      onChange={(e) => onYearFromChange(e.target.value)}
                      className="w-[72px] border border-gray-200 rounded-lg px-2 py-1 text-xs bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
                    />
                    <span className="text-xs text-gray-400">—</span>
                    <input
                      type="number"
                      placeholder="截止年"
                      value={yearTo}
                      onChange={(e) => onYearToChange(e.target.value)}
                      className="w-[72px] border border-gray-200 rounded-lg px-2 py-1 text-xs bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
                    />
                  </div>
                </div>

                <select
                  value={sortBy}
                  onChange={(e) => onSortChange(e.target.value as 'score' | 'title' | 'year')}
                  className="border border-gray-200 rounded-lg px-2.5 py-1 text-xs bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 cursor-pointer"
                >
                  <option value="score">按相关性</option>
                  <option value="year">按年份</option>
                  <option value="title">按标题</option>
                </select>
              </div>

              {/* 论文列表 + 详情面板（跳出居中列，占满页面全宽） */}
              {sortedPapers.length === 0 ? (
                <div className="text-center py-12 text-gray-400 text-sm">
                  {showSelectedOnly ? '暂无入选论文' : '暂无论文结果'}
                </div>
              ) : (
                <div
                  className="relative left-1/2 -translate-x-1/2 px-6"
                  style={{ width: chatWidth ? `${chatWidth}px` : '100vw' }}
                >
                  <PaperResultsPanel
                    papers={sortedPapers}
                    relations={result.relations || []}
                    allPapers={result.papers}
                    traceabilityEnabled={result.traceability_enabled ?? false}
                    taskId={entry.taskId}
                  />
                </div>
              )}
            </div>
          )}

          {/* 成功但无结果 */}
          {isSucceeded && !result && !error && (
            <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md p-8 text-center text-gray-400 text-sm">
              暂无结果数据
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ===== 子组件 =====
function UserMessage({ query, timestamp }: { query: string; timestamp?: string }) {
  return (
    <div className="flex gap-4">
      <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0 mt-0.5">
        <svg className="w-4 h-4 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-800 mb-1">你</p>
        <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-md px-4 py-3 shadow-sm">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{query}</p>
        </div>
        {timestamp && <p className="text-xs text-gray-400 mt-1.5">{formatTime(timestamp)}</p>}
      </div>
    </div>
  )
}

function AssistantAvatar() {
  return (
    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shrink-0 mt-0.5 shadow-md shadow-indigo-200">
      <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; dot: string; label: string }> = {
    running: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500', label: '运行中' },
    queued: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500', label: '排队中' },
    succeeded: { bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500', label: '已完成' },
    failed: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500', label: '失败' },
    cancelled: { bg: 'bg-gray-50', text: 'text-gray-600', dot: 'bg-gray-400', label: '已取消' },
  }
  const c = config[status] || config.queued
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full ${c.bg} ${c.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${status === 'running' ? 'animate-pulse' : ''} ${c.dot}`} />
      {c.label}
    </span>
  )
}

// 总耗时卡片：任务运行中每秒实时刷新（从 started_at 起算，未开始时从 created_at 起算），终态后定格
function DurationStat({ startedAt, createdAt, finishedAt }: { startedAt: string | null; createdAt: string; finishedAt: string | null }) {
  const isDone = !!finishedAt
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (isDone) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isDone])
  const start = startedAt || createdAt
  const end = finishedAt || new Date(now).toISOString()
  return <StatCard label="总耗时" value={calcDuration(start, end)} color="gray" />
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  const colorMap: Record<string, string> = {
    indigo: 'text-indigo-600',
    purple: 'text-purple-600',
    blue: 'text-blue-600',
    gray: 'text-gray-600',
  }
  return (
    <div className="bg-gray-50 rounded-xl p-2.5 text-center border border-gray-100">
      <div className={`text-lg font-bold tabular-nums ${colorMap[color] || colorMap.gray}`}>{value}</div>
      <div className="text-[10px] text-gray-400 mt-0.5">{label}</div>
    </div>
  )
}

// ===== 论文结果面板（三栏布局） =====
function PaperResultsPanel({
  papers,
  relations,
  allPapers,
  traceabilityEnabled,
  taskId,
}: {
  papers: PaperItem[]
  relations: PaperRelation[]
  allPapers: PaperItem[]
  traceabilityEnabled: boolean
  taskId: string
}) {
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null)
  // 全文证据按需加载状态（按 paper_id 隔离）：仅用户主动点击且有 arxiv_id 时才请求
  const [fulltextState, setFulltextState] = useState<Record<string, {
    trace: RecommendationTrace | null
    loaded: boolean
    loading: boolean
    error: string | null
  }>>({})
  // 跳转定位高亮（constraint-xxx / evidence-xxx）
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const highlightTimerRef = useRef<number | null>(null)

  const selectedPaper = papers.find((p) => p.paper_id === selectedPaperId) || null
  // 初始分析不请求全文；全文加载成功后用返回的完整 trace 替换当前 trace
  const selectedTrace = selectedPaper
    ? fulltextState[selectedPaper.paper_id]?.trace ?? selectedPaper.recommendation_trace
    : null

  // traceability_enabled === false 时隐藏追溯和关系区域
  const showSidePanels = traceabilityEnabled && !!selectedPaper

  const paperRelations = selectedPaper
    ? relations.filter(
        (r) => r.from_paper_id === selectedPaper.paper_id || r.to_paper_id === selectedPaper.paper_id
      )
    : []

  const findTitle = (paperId: string) => {
    const p = allPapers.find((pp) => pp.paper_id === paperId)
    return p?.title || paperId
  }

  const handleSelect = (paperId: string) => {
    setSelectedPaperId(selectedPaperId === paperId ? null : paperId)
  }

  // 仅当论文有可用 arxiv_id 且用户主动点击时才请求全文；成功响应无论是否含 fulltext 证据都静默替换
  const handleLoadFulltext = async (paperId: string) => {
    const paper = allPapers.find((p) => p.paper_id === paperId)
    if (!paper?.arxiv_id?.trim()) return
    setFulltextState((prev) => ({
      ...prev,
      [paperId]: { trace: prev[paperId]?.trace ?? null, loaded: false, loading: true, error: null },
    }))
    try {
      const trace = await getPaperTrace(taskId, paperId, true)
      setFulltextState((prev) => ({ ...prev, [paperId]: { trace, loaded: true, loading: false, error: null } }))
    } catch {
      // 请求失败：保留原 trace，仅在按钮附近显示可重试错误
      setFulltextState((prev) => ({
        ...prev,
        [paperId]: { trace: prev[paperId]?.trace ?? null, loaded: false, loading: false, error: '全文证据加载失败，请稍后重试' },
      }))
    }
  }

  // 跳转定位：滚动到目标并短暂高亮
  const scrollToItem = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightId(id)
    if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current)
    highlightTimerRef.current = window.setTimeout(() => setHighlightId(null), 1600)
  }

  useEffect(() => () => {
    if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current)
  }, [])

  return (
    <div className="flex gap-4 items-start justify-center">
      {/* 左栏：相关关系（仅追溯启用且选中论文时显示） */}
      {showSidePanels && (
        <div className="w-[320px] shrink-0 self-stretch animate-fade-in">
          <div className="sticky top-4 space-y-3">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <span className="text-sm font-bold text-gray-700">相关关系</span>
              <span className="text-[11px] text-gray-400">({paperRelations.length})</span>
            </div>
            {paperRelations.length === 0 ? (
              <div className="text-xs text-gray-400 bg-gray-50 rounded-xl border border-gray-100 p-4 text-center">
                当前分析范围内未发现关系
              </div>
            ) : (
              <div className="space-y-2 max-h-[calc(100vh-180px)] overflow-y-auto pr-1">
                {paperRelations.map((rel) => (
                  <RelationCard key={rel.relation_id} relation={rel} findTitle={findTitle} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 中栏：论文列表（保持后端原始顺序，不因是否有追溯结果而重排） */}
      <div className="w-full max-w-3xl min-w-0 space-y-3">
        {papers.map((paper) => (
          <SelectablePaperCard
            key={paper.paper_id}
            paper={paper}
            isSelected={selectedPaperId === paper.paper_id}
            onSelect={() => handleSelect(paper.paper_id)}
            traceabilityEnabled={traceabilityEnabled}
            onNavigateToRef={(targetId) => {
              // 点击卡片理由中的关联标记：选中该论文并定位到右侧面板对应卡片
              setSelectedPaperId(paper.paper_id)
              window.setTimeout(() => scrollToItem(targetId), 120)
            }}
          />
        ))}
      </div>

      {/* 右栏：推荐理由 + 判断依据（仅追溯启用且选中论文时显示） */}
      {showSidePanels && (
        <div className="w-[360px] shrink-0 self-stretch animate-fade-in">
          <div className="sticky top-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <span className="text-sm font-bold text-gray-700">推荐分析</span>
              </div>
              <button
                onClick={() => setSelectedPaperId(null)}
                className="w-5 h-5 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="max-h-[calc(100vh-180px)] overflow-y-auto space-y-3 pr-1">
              {selectedTrace && selectedPaper ? (
                <>
                  {/* 全文证据按需加载区：canLoadFulltext === false 时不显示按钮，也不显示“全文不可用”提示 */}
                  {(() => {
                    const paperId = selectedPaper.paper_id
                    const ft = fulltextState[paperId]
                    const canLoadFulltext =
                      !!selectedPaper.recommendation_trace &&
                      !!selectedPaper.arxiv_id?.trim() &&
                      !ft?.loaded
                    if (ft?.loading) {
                      return (
                        <div className="bg-gray-50 border border-gray-100 rounded-xl px-4 py-2.5 flex items-center gap-2">
                          <svg className="animate-spin w-3.5 h-3.5 text-indigo-500" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                          <span className="text-xs text-gray-500">正在加载全文证据...</span>
                        </div>
                      )
                    }
                    if (!canLoadFulltext && !ft?.error) return null
                    return (
                      <div className="space-y-1.5">
                        {ft?.error && (
                          <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-2 text-xs text-red-600">
                            {ft.error}
                          </div>
                        )}
                        {canLoadFulltext && (
                          <button
                            onClick={() => handleLoadFulltext(paperId)}
                            className="w-full bg-white border border-indigo-200 text-indigo-600 hover:bg-indigo-50 rounded-xl px-4 py-2.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                            </svg>
                            加载全文证据
                          </button>
                        )}
                      </div>
                    )
                  })()}

                  {/* 追溯详情：理由 + 约束 + 证据 + 检索来源，支持跳转定位 */}
                  <TraceDetail
                    trace={selectedTrace}
                    highlightId={highlightId}
                    onNavigate={scrollToItem}
                    hasFulltext={!!selectedTrace.evidence?.some((e) => e.source_type === 'fulltext')}
                  />
                </>
              ) : (
                <div className="text-xs text-gray-400 bg-gray-50 rounded-xl border border-gray-100 p-4 text-center">
                  该论文暂无推荐分析
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ===== 可选中的论文卡片 =====
function SelectablePaperCard({
  paper,
  isSelected,
  onSelect,
  traceabilityEnabled,
  onNavigateToRef,
}: {
  paper: PaperItem
  isSelected: boolean
  onSelect: () => void
  traceabilityEnabled: boolean
  onNavigateToRef?: (targetId: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  // 四类约束数量（有追溯结果时统计）
  const trace = paper.recommendation_trace
  const constraintCounts = trace
    ? [
        { label: '满足', count: trace.satisfied_constraints?.length || 0, cls: 'text-emerald-700 bg-emerald-50 border-emerald-100' },
        { label: '部分满足', count: trace.partially_satisfied_constraints?.length || 0, cls: 'text-amber-700 bg-amber-50 border-amber-100' },
        { label: '未满足', count: trace.violated_constraints?.length || 0, cls: 'text-red-700 bg-red-50 border-red-100' },
        { label: '尚无法确认', count: trace.unknown_constraints?.length || 0, cls: 'text-gray-600 bg-gray-50 border-gray-200' },
      ].filter((c) => c.count > 0)
    : []

  const externalUrl = paper.url || paper.arxiv_url || paper.doi || null
  const linkLabel = paper.url ? '查看' : paper.arxiv_url ? 'arXiv' : paper.doi ? 'DOI' : 'Link'
  const hasAbstract = paper.abstract && paper.abstract.trim().length > 0

  const displayAuthors = paper.authors?.length
    ? paper.authors.length <= 3
      ? paper.authors.join(', ')
      : `${paper.authors.slice(0, 3).join(', ')} 等`
    : null

  return (
    <div
      onClick={onSelect}
      className={`border rounded-xl p-4 transition-all duration-200 cursor-pointer bg-white animate-fade-in ${
        isSelected
          ? 'border-indigo-300 shadow-md ring-2 ring-indigo-100'
          : 'border-gray-100 hover:shadow-md hover:border-indigo-200'
      }`}
    >
      {/* Title + Score */}
      <div className="flex justify-between items-start gap-3">
        <h3 className={`text-[13px] font-semibold flex-1 leading-snug transition-colors ${
          isSelected ? 'text-indigo-700' : 'text-gray-800'
        }`}>
          {paper.title || '无标题'}
        </h3>
        <div className={`shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold font-mono
          ${paper.score >= 0.8 ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
            paper.score >= 0.5 ? 'bg-amber-50 text-amber-700 border border-amber-200' :
            'bg-gray-100 text-gray-600 border border-gray-200'}`}
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
          {scoreToPercent(paper.score)}
        </div>
      </div>

      {/* Authors */}
      {displayAuthors && (
        <p className="mt-1.5 text-[11px] text-gray-500 truncate" title={paper.authors.join(', ')}>
          {displayAuthors}
        </p>
      )}

      {/* Meta tags */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        {paper.publication_year ? (
          <span className="inline-flex items-center gap-1 text-gray-500 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100">
            {paper.publication_year}
          </span>
        ) : (
          <span className="text-gray-400 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">年份未知</span>
        )}
        {paper.venue && (
          <span className="text-gray-500 bg-purple-50 px-2 py-0.5 rounded-md border border-purple-100 truncate max-w-[180px]">{paper.venue}</span>
        )}
        {paper.cited_by_count > 0 && (
          <span className="text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">引用 {paper.cited_by_count}</span>
        )}
        <span className="text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">{paper.source}</span>
        <span className="text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">Depth {paper.depth}</span>
        {paper.selected && (
          <span className="inline-flex items-center gap-0.5 text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-100 font-semibold">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            入选
          </span>
        )}
        {paper.abstract_status === 'enriched' && (
          <span className="text-blue-700 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100">
            已补全{abstractSourceLabels[paper.abstract_source] ? ` · ${abstractSourceLabels[paper.abstract_source]}` : ''}
          </span>
        )}
        {paper.abstract_status === 'unavailable' && (
          <span className="text-gray-400 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-200 italic">摘要暂不可用</span>
        )}
      </div>

      {/* Abstract */}
      <div className="mt-2.5">
        {hasAbstract ? (
          <p
            className={`text-[12px] text-gray-600 leading-relaxed ${expanded ? '' : 'line-clamp-3'}`}
            style={{ wordBreak: 'break-word' }}
          >
            {paper.abstract}
          </p>
        ) : (
          <p className="text-[12px] text-gray-400 italic">暂无摘要</p>
        )}
      </div>

      {/* 推荐理由 + 四类约束数量（仅追溯启用且有追溯结果时显示） */}
      {traceabilityEnabled && trace && (constraintCounts.length > 0 || (trace.reasons && trace.reasons.length > 0)) && (
        <div className="mt-2.5 bg-indigo-50/50 border border-indigo-100 rounded-lg px-3 py-2 space-y-1.5">
          {constraintCounts.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {constraintCounts.map((c) => (
                <span key={c.label} className={`text-[10px] border rounded px-1.5 py-0.5 ${c.cls}`}>
                  {c.label} {c.count}
                </span>
              ))}
            </div>
          )}
          {(trace.reasons || []).slice(0, 2).map((reason, i) => (
            <div key={i}>
              <p className="text-[12px] text-indigo-800 leading-relaxed">
                <span className="font-semibold">推荐理由{i + 1}：</span>
                {reason.text}
              </p>
              {(reason.constraint_ids?.length > 0 || reason.evidence_ids?.length > 0) && onNavigateToRef && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {reason.constraint_ids.map((cid) => (
                    <RefChip key={`c-${cid}`} label={`约束 ${shortId(cid)}`} onClick={() => onNavigateToRef(`constraint-${cid}`)} />
                  ))}
                  {reason.evidence_ids.map((eid) => (
                    <RefChip key={`e-${eid}`} label={`证据 ${shortId(eid)}`} onClick={() => onNavigateToRef(`evidence-${eid}`)} />
                  ))}
                </div>
              )}
            </div>
          ))}
          {(trace.reasons?.length || 0) > 2 && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onSelect()
              }}
              className="text-[11px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors"
            >
              查看全部 {trace.reasons.length} 条理由 →
            </button>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="mt-2 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
        {hasAbstract ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            <svg
              className={`w-3 h-3 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
            {expanded ? '收起' : '展开摘要'}
          </button>
        ) : (
          <span />
        )}

        {externalUrl && (
          <a
            href={externalUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-400 hover:text-indigo-600 transition-colors"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
            {linkLabel}
          </a>
        )}
      </div>
    </div>
  )
}

// ===== 摘要补全来源标签 =====
const abstractSourceLabels: Record<string, string> = {
  openalex: 'OpenAlex',
  arxiv: 'arXiv',
  semantic_scholar: 'Semantic Scholar',
  crossref: 'Crossref',
  model_result: '模型结果',
}

// ===== 关系类型中文标签 =====
const relationTypeLabels: Record<RelationType, string> = {
  cites: '引用',
  cited_by: '被引用',
  same_method: '方法相同',
  extends_method: '方法扩展',
  same_task: '任务相同',
  same_dataset: '数据集相同',
}

// ===== 关系卡片（confirmed 实线 / inferred 虚线；cites 有向 / same_* 无向） =====
function RelationCard({
  relation,
  findTitle,
}: {
  relation: PaperRelation
  findTitle: (id: string) => string
}) {
  const isDirected = relation.type === 'cites' || relation.type === 'cited_by'
  const isInferred = relation.relation_class === 'inferred'

  return (
    <div className={`bg-white rounded-xl px-3 py-2.5 text-xs shadow-sm ${
      isInferred ? 'border border-dashed border-gray-300' : 'border border-gray-100'
    }`}>
      <div className="flex items-center justify-between mb-1 gap-1">
        <div className="flex items-center gap-1 min-w-0">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
          <span className="font-semibold text-blue-600 truncate">{relationTypeLabels[relation.type] || relation.type}</span>
          {isInferred && (
            <span className="text-[10px] text-gray-400 bg-gray-50 border border-gray-200 rounded px-1 shrink-0">推断</span>
          )}
        </div>
        {relation.confidence != null && (
          <span className="text-[10px] font-mono text-gray-400 shrink-0">{Math.round(relation.confidence * 100)}%</span>
        )}
      </div>
      <p className="text-gray-600 line-clamp-2 font-medium">{findTitle(relation.from_paper_id)}</p>
      <div className="flex items-center gap-1 my-1 text-blue-400">
        {isDirected ? (
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
        ) : (
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
        )}
        <span className="text-[10px] text-gray-400">{isDirected ? (relation.type === 'cited_by' ? '被引 →' : '引用 →') : '无向'}</span>
      </div>
      <p className="text-gray-600 line-clamp-2 font-medium">{findTitle(relation.to_paper_id)}</p>
      {relation.description && (
        <p className="text-gray-400 mt-1.5 text-[11px]">{relation.description}</p>
      )}
    </div>
  )
}

// ===== 四种约束状态颜色（satisfied 绿 / partially_satisfied 黄 / violated 红 / unknown 灰） =====
const constraintStatusColors: Record<ConstraintStatus, { dot: string; text: string; bg: string; border: string }> = {
  satisfied: { dot: 'bg-emerald-500', text: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-100' },
  partially_satisfied: { dot: 'bg-amber-500', text: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-100' },
  violated: { dot: 'bg-red-500', text: 'text-red-700', bg: 'bg-red-50', border: 'border-red-100' },
  unknown: { dot: 'bg-gray-400', text: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' },
}

const sourceTypeLabels: Record<string, string> = {
  title: '标题',
  abstract: '摘要',
  fulltext: '全文',
  metadata: '元数据',
  citation_database: '引用数据库',
}

// ===== 短 ID 显示 =====
function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id
}

// ===== 引用跳转 chip（理由/约束/证据之间互相定位） =====
function RefChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      title="点击跳转定位"
      className="text-[10px] font-mono text-indigo-600 bg-white hover:bg-indigo-50 border border-indigo-200 hover:border-indigo-300 rounded px-1.5 py-0.5 transition-colors shrink-0"
    >
      {label}
    </button>
  )
}

// ===== 推荐分析详情（理由 + 约束 + 证据，支持 constraint_ids / evidence_ids 跳转） =====
function TraceDetail({
  trace,
  highlightId,
  onNavigate,
  hasFulltext,
}: {
  trace: RecommendationTrace
  highlightId: string | null
  onNavigate: (id: string) => void
  hasFulltext: boolean
}) {
  const groups: { title: string; items: ConstraintAssessment[]; status: ConstraintStatus }[] = [
    { title: '满足', items: trace.satisfied_constraints || [], status: 'satisfied' },
    { title: '部分满足', items: trace.partially_satisfied_constraints || [], status: 'partially_satisfied' },
    { title: '未满足', items: trace.violated_constraints || [], status: 'violated' },
    { title: '尚无法确认', items: trace.unknown_constraints || [], status: 'unknown' },
  ]
  const totalConstraintCount = groups.reduce((sum, g) => sum + g.items.length, 0)
  // 展示顺序：标题/摘要/元数据证据在前，按需加载到的全文证据在后（组内保持后端原始顺序）
  const evidenceList = [...(trace.evidence || [])].sort(
    (a, b) => (a.source_type === 'fulltext' ? 1 : 0) - (b.source_type === 'fulltext' ? 1 : 0)
  )
  const retrievalSources = trace.retrieval_sources || []

  return (
    <div className="space-y-3">
      {/* 推荐理由 */}
      {trace.reasons?.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-bold text-gray-500 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
            推荐理由 ({trace.reasons.length})
          </p>
          {trace.reasons.map((reason, i) => (
            <ReasonCard key={i} reason={reason} onNavigate={onNavigate} />
          ))}
        </div>
      )}

      {/* 约束分组 */}
      {totalConstraintCount > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-bold text-gray-500">判断依据</p>
          {groups.map((g) => (
            <ConstraintGroup
              key={g.status}
              title={g.title}
              items={g.items}
              status={g.status}
              highlightId={highlightId}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}

      {/* 证据列表 */}
      {evidenceList.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-bold text-gray-500 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
            证据 ({evidenceList.length})
            {hasFulltext && (
              <span className="text-[10px] font-normal text-emerald-600 bg-emerald-50 border border-emerald-100 rounded px-1">含全文</span>
            )}
          </p>
          {evidenceList.map((ev) => (
            <EvidenceCard key={ev.evidence_id} evidence={ev} highlightId={highlightId} onNavigate={onNavigate} />
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-400 bg-gray-50 rounded-xl border border-gray-100 p-3 text-center">
          暂无可展示的标题或摘要证据
        </div>
      )}

      {/* 检索来源 */}
      {retrievalSources.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-bold text-gray-500">检索来源</p>
          <div className="flex flex-wrap gap-1.5">
            {retrievalSources.map((src) => (
              <span key={src} className="text-[11px] text-gray-500 bg-gray-50 border border-gray-200 rounded-md px-2 py-0.5">
                {src}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ===== 推荐理由卡片（含约束/证据引用跳转） =====
function ReasonCard({ reason, onNavigate }: { reason: RecommendationReason; onNavigate: (id: string) => void }) {
  return (
    <div className="bg-indigo-50/70 border border-indigo-100 rounded-xl px-3.5 py-2.5">
      <p className="text-xs text-indigo-800 leading-relaxed">{reason.text}</p>
      {(reason.constraint_ids?.length > 0 || reason.evidence_ids?.length > 0) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {reason.constraint_ids.map((cid) => (
            <RefChip key={`c-${cid}`} label={`约束 ${shortId(cid)}`} onClick={() => onNavigate(`constraint-${cid}`)} />
          ))}
          {reason.evidence_ids.map((eid) => (
            <RefChip key={`e-${eid}`} label={`证据 ${shortId(eid)}`} onClick={() => onNavigate(`evidence-${eid}`)} />
          ))}
        </div>
      )}
    </div>
  )
}

// ===== 约束分组（按状态着色，unknown 显示为"未知"而非"不满足"） =====
function ConstraintGroup({
  title,
  items,
  status,
  highlightId,
  onNavigate,
}: {
  title: string
  items: ConstraintAssessment[]
  status: ConstraintStatus
  highlightId: string | null
  onNavigate: (id: string) => void
}) {
  if (!items || items.length === 0) return null
  const c = constraintStatusColors[status]

  return (
    <div>
      <p className={`text-[11px] font-semibold ${c.text} mb-1 flex items-center gap-1`}>
        <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
        {title} ({items.length})
      </p>
      <div className="space-y-1 ml-2.5">
        {items.map((item) => {
          const id = `constraint-${item.constraint_id}`
          const highlighted = highlightId === id
          return (
            <div
              key={item.constraint_id}
              id={id}
              className={`${c.bg} border ${c.border} rounded-lg px-2.5 py-1.5 transition-all duration-300 ${
                highlighted ? 'ring-2 ring-indigo-400 shadow-md' : ''
              }`}
            >
              <p className="text-xs font-medium text-gray-700">{item.constraint_id}</p>
              <p className="text-[11px] text-gray-500 mt-0.5">{item.explanation}</p>
              {item.evidence_ids?.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {item.evidence_ids.map((eid) => (
                    <RefChip key={eid} label={`证据 ${shortId(eid)}`} onClick={() => onNavigate(`evidence-${eid}`)} />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ===== 证据卡片（exact_text / location / source_type / source / source_url / confidence） =====
function EvidenceCard({
  evidence,
  highlightId,
  onNavigate,
}: {
  evidence: Evidence
  highlightId: string | null
  onNavigate: (id: string) => void
}) {
  const id = `evidence-${evidence.evidence_id}`
  const highlighted = highlightId === id
  const isFulltext = evidence.source_type === 'fulltext'

  return (
    <div
      id={id}
      className={`bg-white border rounded-xl px-3 py-2.5 text-xs shadow-sm transition-all duration-300 ${
        highlighted ? 'border-indigo-300 ring-2 ring-indigo-100 shadow-md' : 'border-gray-100'
      }`}
    >
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 ${
          isFulltext ? 'bg-indigo-50 text-indigo-600 border border-indigo-100' : 'bg-gray-50 text-gray-500 border border-gray-200'
        }`}>
          {sourceTypeLabels[evidence.source_type] || evidence.source_type}
        </span>
        {evidence.confidence != null && (
          <span className="text-[10px] text-gray-400 font-mono shrink-0">置信度 {Math.round(evidence.confidence * 100)}%</span>
        )}
        {evidence.location && <span className="text-[10px] text-gray-400 truncate">{evidence.location}</span>}
      </div>
      <p className="text-gray-600 leading-relaxed" style={{ wordBreak: 'break-word' }}>{evidence.exact_text}</p>
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="text-[10px] text-gray-400 truncate">{evidence.source}</span>
        {evidence.source_url && (
          <a
            href={evidence.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-indigo-500 hover:underline shrink-0 inline-flex items-center gap-0.5"
          >
            来源 ↗
          </a>
        )}
      </div>
      {evidence.constraint_ids?.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {evidence.constraint_ids.map((cid) => (
            <RefChip key={cid} label={`约束 ${shortId(cid)}`} onClick={() => onNavigate(`constraint-${cid}`)} />
          ))}
        </div>
      )}
    </div>
  )
}
