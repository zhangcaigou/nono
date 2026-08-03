import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHealth, createSearchTask } from '@/api/search'
import { HealthResponse } from '@/types'
import ChatInput from '@/components/ChatInput'
import { addTaskToHistory } from '@/components/Sidebar'

export default function SearchPage() {
  const navigate = useNavigate()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [isHealthLoading, setIsHealthLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    const check = async () => {
      setIsHealthLoading(true)
      try {
        const data = await getHealth()
        setHealth(data)
      } catch {
        setHealth(null)
      } finally {
        setIsHealthLoading(false)
      }
    }
    void check()
  }, [])

  const isReady = health?.ready ?? false

  const handleSubmit = async (query: string, opts?: any) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    setSubmitError('')

    try {
      const accepted = await createSearchTask({
        query,
        end_date: opts?.end_date || null,
        options: opts?.options,
      })
      addTaskToHistory(accepted.task_id, query)
      navigate(`/tasks/${accepted.task_id}`)
    } catch (err: any) {
      const errorData = err.response?.data?.error
      if (errorData) {
        setSubmitError(`[${errorData.code}] ${errorData.message}`)
      } else if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
        setSubmitError('网络连接失败，请检查后端服务是否正常运行')
      } else if (err.code === 'ECONNABORTED') {
        setSubmitError('请求超时，后端响应过慢，请稍后重试')
      } else if (err.message) {
        setSubmitError(err.message)
      } else {
        setSubmitError('创建任务失败，请检查网络或稍后重试')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  // 问题池（随机抽取 4 个展示）
  const questionPool = [
    '大语言模型在医疗诊断中的最新进展',
    'CRISPR 基因编辑在癌症治疗中的应用',
    '强化学习在机器人控制中的前沿方法',
    'Transformer 架构的注意力机制优化研究',
    '扩散模型在图像生成领域的技术突破',
    '图神经网络在药物分子筛选中的应用',
    '联邦学习在隐私保护下的分布式训练',
    '多模态大模型的视觉语言理解能力',
    '量子计算在密码学中的潜在威胁与应对',
    '自监督学习在小样本场景下的表现',
    '神经辐射场 NeRF 在三维重建中的进展',
    '大模型思维链推理能力的提升方法',
    '蛋白质结构预测的深度学习方法',
    '自动驾驶中的端到端决策规划研究',
    '检索增强生成 RAG 的关键技术',
    'AI  Agent 在复杂任务规划中的能力边界',
  ]

  const shuffleQuestions = () => {
    const shuffled = [...questionPool].sort(() => Math.random() - 0.5)
    return shuffled.slice(0, 4)
  }

  const [exampleQueries, setExampleQueries] = useState<string[]>(shuffleQuestions)

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 overflow-y-auto">
        <div className="w-full max-w-2xl animate-fade-in">
          {/* Logo & Welcome */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 shadow-lg shadow-indigo-200 mb-5">
              <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            </div>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">
              你好，我是 <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600">NoNo</span>
            </h1>
            <p className="text-base text-gray-500">
              学术论文智能检索 · AI 驱动 · 引用扩展 · 深度发现
            </p>
          </div>

          {/* Service status */}
          {!isHealthLoading && (
            <div className="mb-6 animate-slide-up">
              {!health && (
                <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-xl px-4 py-3 border border-red-100">
                  <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  无法连接后端服务，请检查后端是否已启动
                </div>
              )}
              {health && !health.ready && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm">
                  <div className="flex items-start gap-2">
                    <svg className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div>
                      <p className="font-semibold text-amber-800">搜索服务尚未就绪</p>
                      {health.reasons.length > 0 && (
                        <ul className="mt-1 space-y-0.5 text-amber-700">
                          {health.reasons.map((r, i) => (
                            <li key={i} className="flex items-center gap-1.5">
                              <span className="w-1 h-1 rounded-full bg-amber-400 shrink-0" />
                              {r}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Submit error */}
          {submitError && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700 animate-scale-in">
              <div className="flex items-start gap-2">
                <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>{submitError}</span>
              </div>
            </div>
          )}

          {/* Input */}
          <div className="animate-slide-up" style={{ animationDelay: '0.1s' }}>
            <ChatInput
              onSubmit={handleSubmit}
              isSubmitting={isSubmitting}
              disabled={!isReady}
              placeholder="输入您的学术检索问题，AI 将为您深度检索相关论文..."
              showAdvanced
            />
          </div>

          {/* Example queries */}
          <div className="mt-8 animate-slide-up" style={{ animationDelay: '0.2s' }}>
            <div className="flex items-center justify-center gap-2 mb-3">
              <p className="text-xs text-gray-400">试试这些问题</p>
              <button
                onClick={() => setExampleQueries(shuffleQuestions())}
                className="p-1 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                title="换一批"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {exampleQueries.map((q, i) => (
                <button
                  key={i}
                  onClick={() => handleSubmit(q)}
                  disabled={!isReady || isSubmitting}
                  className="text-left text-sm text-gray-600 bg-white border border-gray-150 rounded-xl px-4 py-3 
                    hover:border-indigo-200 hover:bg-indigo-50/50 hover:text-indigo-700 
                    transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed
                    hover:shadow-sm"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* Features */}
          <div className="mt-12 grid grid-cols-3 gap-4 animate-slide-up" style={{ animationDelay: '0.3s' }}>
            <div className="text-center">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center mx-auto mb-2">
                <svg className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              <p className="text-xs font-medium text-gray-600">智能检索</p>
              <p className="text-[10px] text-gray-400 mt-0.5">多检索词组合搜索</p>
            </div>
            <div className="text-center">
              <div className="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center mx-auto mb-2">
                <svg className="w-5 h-5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <p className="text-xs font-medium text-gray-600">相关性评估</p>
              <p className="text-[10px] text-gray-400 mt-0.5">AI 评分筛选论文</p>
            </div>
            <div className="text-center">
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center mx-auto mb-2">
                <svg className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <p className="text-xs font-medium text-gray-600">引用扩展</p>
              <p className="text-[10px] text-gray-400 mt-0.5">沿引用关系深度发现</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
