import { useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { HealthResponse } from '@/types'
import { getHealth } from '@/api/search'

interface TaskHistoryItem {
  taskId: string
  query: string
  timestamp: number
}

function getTaskHistory(): TaskHistoryItem[] {
  try {
    const raw = localStorage.getItem('NoNo_task_history')
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export function addTaskToHistory(taskId: string, query: string) {
  try {
    const history = getTaskHistory()
    const filtered = history.filter((h) => h.taskId !== taskId)
    filtered.unshift({ taskId, query, timestamp: Date.now() })
    // 最多保留 50 条
    localStorage.setItem('NoNo_task_history', JSON.stringify(filtered.slice(0, 50)))
  } catch {
    // ignore
  }
}

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [history, setHistory] = useState<TaskHistoryItem[]>([])
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 768)

  useEffect(() => {
    setHistory(getTaskHistory())
  }, [location.pathname])

  useEffect(() => {
    const check = async () => {
      try {
        const data = await getHealth()
        setHealth(data)
      } catch {
        setHealth(null)
      }
    }
    void check()
    const interval = setInterval(() => void check(), 30000)
    return () => clearInterval(interval)
  }, [])

  const isReady = health?.ready ?? false
  const currentTaskId = location.pathname.startsWith('/tasks/')
    ? location.pathname.split('/tasks/')[1]
    : null

  const clearHistory = () => {
    localStorage.removeItem('NoNo_task_history')
    setHistory([])
  }

  const removeFromHistory = (taskId: string) => {
    const updated = history.filter((h) => h.taskId !== taskId)
    localStorage.setItem('NoNo_task_history', JSON.stringify(updated))
    setHistory(updated)
    // 如果删除的是当前正在查看的任务，回到首页
    if (currentTaskId === taskId) {
      navigate('/')
    }
  }

  return (
    <aside
      className={`flex flex-col h-screen bg-[#0d1117] text-gray-300 transition-all duration-300 ${
        collapsed ? 'w-16' : 'w-64'
      }`}
    >
      {/* Logo */}
      <div className={`flex items-center gap-3 px-4 py-5 ${collapsed ? 'justify-center' : ''}`}>
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shrink-0 shadow-lg shadow-indigo-500/20">
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <h1 className="text-lg font-bold text-white tracking-tight">NoNo</h1>
            <p className="text-[10px] text-gray-500 -mt-0.5">Academic Search</p>
          </div>
        )}
      </div>

      {/* New Search Button */}
      <div className={`px-3 ${collapsed ? 'flex justify-center' : ''}`}>
        <button
          onClick={() => navigate('/')}
          className={`flex items-center gap-2 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] transition-all duration-200 text-sm font-medium text-gray-200 ${
            collapsed ? 'w-10 h-10 justify-center' : 'w-full px-3.5 py-2.5'
          }`}
        >
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          {!collapsed && <span>新建搜索</span>}
        </button>
      </div>

      {/* Divider */}
      <div className={`my-4 border-t border-white/[0.06] ${collapsed ? 'mx-3' : 'mx-4'}`} />

      {/* History */}
      {!collapsed && (
        <div className="flex-1 flex flex-col min-h-0 px-3">
          <div className="flex items-center justify-between px-1 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">搜索历史</span>
            {history.length > 0 && (
              <button
                onClick={clearHistory}
                className="text-[10px] text-gray-600 hover:text-gray-400 transition-colors"
                title="清空历史"
              >
                清空
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto space-y-0.5 pr-1 sidebar-scroll">
            {history.length === 0 && (
              <p className="text-xs text-gray-600 px-1 py-4 text-center">暂无搜索记录</p>
            )}
            {history.map((item) => (
              <div
                key={item.taskId}
                className={`group flex items-center rounded-lg transition-all duration-150 ${
                  currentTaskId === item.taskId
                    ? 'bg-white/[0.1] text-white'
                    : 'text-gray-400 hover:bg-white/[0.05] hover:text-gray-200'
                }`}
              >
                <button
                  onClick={() => navigate(`/tasks/${item.taskId}`)}
                  className="flex-1 min-w-0 text-left px-3 py-2.5 text-sm truncate"
                  title={item.query}
                >
                  <div className="flex items-center gap-2">
                    <svg className="w-3.5 h-3.5 shrink-0 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <span className="truncate">{item.query}</span>
                  </div>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    removeFromHistory(item.taskId)
                  }}
                  className="shrink-0 w-6 h-6 mr-1.5 rounded-md flex items-center justify-center
                    text-gray-600 opacity-0 group-hover:opacity-100
                    hover:text-red-400 hover:bg-white/[0.08]
                    transition-all duration-150"
                  title="删除此条记录"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Collapsed mode: history icon */}
      {collapsed && (
        <div className="flex-1 flex flex-col items-center py-2 space-y-1">
          {history.slice(0, 5).map((item) => (
            <button
              key={item.taskId}
              onClick={() => navigate(`/tasks/${item.taskId}`)}
              className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
                currentTaskId === item.taskId
                  ? 'bg-white/[0.1] text-white'
                  : 'text-gray-600 hover:text-gray-400 hover:bg-white/[0.05]'
              }`}
              title={item.query}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </button>
          ))}
        </div>
      )}

      {/* Bottom: Status + Collapse */}
      <div className={`mt-auto border-t border-white/[0.06] p-3 ${collapsed ? 'flex flex-col items-center gap-2' : ''}`}>
        {!collapsed && (
          <div className="flex items-center gap-2 px-1 mb-2">
            <span className={`relative flex h-2 w-2`}>
              {isReady && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isReady ? 'bg-emerald-500' : health === null ? 'bg-red-500' : 'bg-amber-500'}`} />
            </span>
            <span className="text-[11px] text-gray-500">
              {health === null ? '服务离线' : isReady ? '服务就绪' : '服务异常'}
            </span>
            {health && health.model_service_ready !== undefined && (
              <span className="text-[10px] text-gray-600 font-mono ml-auto">
                {health.model_service_ready ? '模型就绪' : 'Mock'}
              </span>
            )}
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={`rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/[0.05] transition-colors flex items-center justify-center ${
            collapsed ? 'w-10 h-10' : 'w-full py-2'
          }`}
        >
          <svg
            className={`w-4 h-4 transition-transform duration-300 ${collapsed ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>
    </aside>
  )
}
