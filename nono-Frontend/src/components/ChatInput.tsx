import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { validateQuery } from '@/utils/validation'

interface ChatInputProps {
  onSubmit: (query: string, options?: any) => void
  isSubmitting: boolean
  disabled?: boolean
  placeholder?: string
  showAdvanced?: boolean
}

export default function ChatInput({ onSubmit, isSubmitting, disabled, placeholder, showAdvanced = false }: ChatInputProps) {
  const [query, setQuery] = useState('')
  const [endDate, setEndDate] = useState('')
  const [validationError, setValidationError] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [options, setOptions] = useState({
    expand_layers: 2,
    search_queries: 5,
    search_papers: 10,
    expand_papers: 20,
  })
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 160) + 'px'
    }
  }, [query])

  const handleSubmit = () => {
    const trimmed = query.trim()
    const valid = validateQuery(trimmed)
    if (!valid.valid) {
      setValidationError(valid.message || '无效输入')
      return
    }
    setValidationError('')
    onSubmit(trimmed, { end_date: endDate, options: { ...options } })
    setQuery('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const rangeSlider = (label: string, key: string, min: number, max: number) => (
    <div key={key} className="flex items-center gap-3">
      <span className="text-xs text-gray-500 w-28 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        value={options[key as keyof typeof options]}
        onChange={(e) => setOptions((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
        className="flex-1 h-1"
      />
      <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full min-w-[28px] text-center tabular-nums">
        {options[key as keyof typeof options]}
      </span>
    </div>
  )

  return (
    <div className="w-full">
      {/* Advanced options (collapsible) */}
      {showAdvanced && (
        <div className={`overflow-hidden transition-all duration-300 ${advancedOpen ? 'max-h-64 opacity-100 mb-3' : 'max-h-0 opacity-0'}`}>
          <div className="bg-gray-50 rounded-xl p-4 space-y-2.5 border border-gray-100">
            {rangeSlider('扩展层数', 'expand_layers', 0, 4)}
            {rangeSlider('检索词数量', 'search_queries', 1, 10)}
            {rangeSlider('每词论文数', 'search_papers', 1, 30)}
            {rangeSlider('每层扩展数', 'expand_papers', 1, 50)}
            <div className="flex items-center gap-3 pt-1">
              <span className="text-xs text-gray-500 w-28 shrink-0">截止日期</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
              />
            </div>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="relative bg-white border border-gray-200 rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 focus-within:shadow-md focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-50">
        <textarea
          ref={textareaRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            if (validationError) setValidationError('')
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || '输入您的学术检索问题...'}
          disabled={disabled || isSubmitting}
          rows={1}
          className="w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none disabled:opacity-50"
          style={{ minHeight: '52px', maxHeight: '160px' }}
        />

        <div className="flex items-center justify-between px-3 pb-2.5">
          <div className="flex items-center gap-1">
            {showAdvanced && (
              <button
                onClick={() => setAdvancedOpen(!advancedOpen)}
                className={`p-1.5 rounded-lg text-xs transition-colors ${
                  advancedOpen ? 'bg-indigo-50 text-indigo-600' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                }`}
                title="高级参数"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
              </button>
            )}
            <span className="text-xs text-gray-400 tabular-nums ml-1">
              {query.length}/2000
            </span>
          </div>

          <div className="flex items-center gap-2">
            {query.trim() && (
              <span className="text-[10px] text-gray-400 hidden sm:block">Enter 发送</span>
            )}
            <button
              onClick={handleSubmit}
              disabled={!query.trim() || isSubmitting || disabled}
              className={`w-8 h-8 rounded-xl flex items-center justify-center transition-all duration-200 ${
                !query.trim() || isSubmitting || disabled
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-indigo-600 text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 hover:shadow-lg hover:shadow-indigo-300 hover:-translate-y-0.5'
              }`}
            >
              {isSubmitting ? (
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Validation error */}
      {validationError && (
        <p className="mt-1.5 text-xs text-red-500 flex items-center gap-1 px-1">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {validationError}
        </p>
      )}
    </div>
  )
}
