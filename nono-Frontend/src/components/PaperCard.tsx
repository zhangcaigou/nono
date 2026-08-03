import { PaperItem, ConstraintAssessment, RecommendationTrace, RecommendationReason } from '@/types'
import { scoreToPercent } from '@/utils/format'
import { useState } from 'react'

interface Props {
  paper: PaperItem
}

export default function PaperCard({ paper }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)

  const externalUrl = paper.url || paper.arxiv_url || paper.doi || null
  const linkLabel = paper.url ? '查看' : paper.arxiv_url ? 'arXiv' : paper.doi ? 'DOI' : 'Link'

  const hasAbstract = paper.abstract && paper.abstract.trim().length > 0

  const displayAuthors = paper.authors?.length
    ? paper.authors.length <= 3
      ? paper.authors.join(', ')
      : `${paper.authors.slice(0, 3).join(', ')} 等`
    : null

  const trace: RecommendationTrace | null = paper.recommendation_trace

  const hasTrace =
    trace != null &&
    (trace.satisfied_constraints?.length > 0 ||
      trace.partially_satisfied_constraints?.length > 0 ||
      trace.violated_constraints?.length > 0 ||
      trace.unknown_constraints?.length > 0 ||
      trace.reasons?.length > 0)

  // 摘要状态标签
  const abstractBadge = (() => {
    if (paper.abstract_status === 'enriched') {
      return (
        <span className="inline-flex items-center gap-0.5 text-blue-700 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
          </svg>
          已补全 · {paper.abstract_source}
        </span>
      )
    }
    if (paper.abstract_status === 'unavailable') {
      return (
        <span className="text-gray-400 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-200 italic">
          摘要暂不可用
        </span>
      )
    }
    return null
  })()

  return (
    <div className="group border border-gray-100 rounded-xl p-4 transition-all duration-200
      hover:shadow-md hover:border-indigo-200 bg-white animate-fade-in">

      {/* Title + Score */}
      <div className="flex justify-between items-start gap-3">
        <h3 className="text-sm font-semibold text-gray-800 flex-1 leading-snug group-hover:text-indigo-700 transition-colors">
          {externalUrl ? (
            <a href={externalUrl} target="_blank" rel="noopener noreferrer" className="hover:underline">
              {paper.title || '无标题'}
            </a>
          ) : (
            paper.title || '无标题'
          )}
        </h3>
        <div className={`shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold font-mono
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
        <p className="mt-1.5 text-xs text-gray-500 truncate" title={paper.authors.join(', ')}>
          {displayAuthors}
        </p>
      )}

      {/* Meta tags */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        {paper.publication_year ? (
          <span className="inline-flex items-center gap-1 text-gray-500 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            {paper.publication_year}
          </span>
        ) : (
          <span className="text-gray-400 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">年份未知</span>
        )}
        {paper.venue && (
          <span className="text-gray-500 bg-purple-50 px-2 py-0.5 rounded-md border border-purple-100 truncate max-w-[180px]" title={paper.venue}>
            {paper.venue}
          </span>
        )}
        {paper.cited_by_count > 0 && (
          <span className="inline-flex items-center gap-0.5 text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100" title="被引用次数">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
            </svg>
            {paper.cited_by_count}
          </span>
        )}
        <span className="text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">
          {paper.source}
        </span>
        <span className="text-gray-500 bg-gray-50 px-2 py-0.5 rounded-md border border-gray-100">
          Depth {paper.depth}
        </span>
        {paper.selected && (
          <span className="inline-flex items-center gap-0.5 text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-100 font-semibold">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            入选
          </span>
        )}
        {abstractBadge}
      </div>

      {/* Abstract */}
      <div className="mt-2.5">
        {hasAbstract ? (
          <p
            className={`text-xs text-gray-600 leading-relaxed ${expanded ? '' : 'line-clamp-3'}`}
            style={{ wordBreak: 'break-word' }}
          >
            {paper.abstract}
          </p>
        ) : (
          <p className="text-xs text-gray-400 italic">暂无摘要</p>
        )}
      </div>

      {/* 推荐理由 */}
      {trace?.reasons && trace.reasons.length > 0 && (
        <div className="mt-2.5 bg-indigo-50/50 border border-indigo-100 rounded-lg px-3 py-2 space-y-1.5">
          {trace.reasons.map((reason: RecommendationReason, i: number) => (
            <p key={i} className="text-xs text-indigo-800 leading-relaxed">
              <span className="font-semibold">推荐理由{i + 1}：</span>
              {reason.text}
            </p>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {hasAbstract && (
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
          )}
          {hasTrace && (
            <button
              onClick={() => setTraceOpen(!traceOpen)}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500 hover:text-indigo-600 transition-colors"
            >
              <svg
                className={`w-3 h-3 transition-transform duration-300 ${traceOpen ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
              查看判断依据
            </button>
          )}
        </div>

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

      {/* 判断依据折叠区 */}
      {traceOpen && trace && (
        <div className="mt-3 border-t border-gray-100 pt-3 space-y-3 animate-fade-in">
          {trace.reasons?.length > 0 && (
            <ReasonGroup reasons={trace.reasons} />
          )}
          <ConstraintGroup
            title="满足的约束"
            constraints={trace.satisfied_constraints}
            status="satisfied"
          />
          <ConstraintGroup
            title="部分满足的约束"
            constraints={trace.partially_satisfied_constraints}
            status="partially_satisfied"
          />
          <ConstraintGroup
            title="违反的约束"
            constraints={trace.violated_constraints}
            status="violated"
          />
          <ConstraintGroup
            title="未知的约束"
            constraints={trace.unknown_constraints}
            status="unknown"
          />
        </div>
      )}
    </div>
  )
}

// ===== 推荐理由分组 =====
function ReasonGroup({ reasons }: { reasons: RecommendationReason[] }) {
  return (
    <div>
      <p className="text-xs font-semibold text-indigo-700 mb-1.5 flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
        推荐理由 ({reasons.length})
      </p>
      <div className="space-y-1.5 ml-3">
        {reasons.map((reason, i) => (
          <div key={i} className="bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-700 leading-relaxed">{reason.text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ===== 约束分组组件 =====
function ConstraintGroup({
  title,
  constraints,
  status,
}: {
  title: string
  constraints: ConstraintAssessment[]
  status: 'satisfied' | 'partially_satisfied' | 'violated' | 'unknown'
}) {
  const colorMap: Record<string, { dot: string; text: string; bg: string; border: string }> = {
    satisfied: { dot: 'bg-emerald-500', text: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-100' },
    partially_satisfied: { dot: 'bg-amber-500', text: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-100' },
    violated: { dot: 'bg-red-500', text: 'text-red-700', bg: 'bg-red-50', border: 'border-red-100' },
    unknown: { dot: 'bg-gray-400', text: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' },
  }
  const c = colorMap[status]
  const items = constraints || []

  if (items.length === 0) return null

  return (
    <div>
      <p className={`text-xs font-semibold ${c.text} mb-1.5 flex items-center gap-1.5`}>
        <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
        {title} ({items.length})
      </p>
      <div className="space-y-1.5 ml-3">
        {items.map((item, i) => (
          <div key={i} className={`${c.bg} border ${c.border} rounded-lg px-3 py-2`}>
            <p className="text-xs font-medium text-gray-700">{item.constraint_id}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">{item.explanation}</p>
            {item.evidence_ids?.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {item.evidence_ids.map((eid, j) => (
                  <span key={j} className="text-[10px] font-mono text-gray-400 bg-white px-1.5 py-0.5 rounded border border-gray-200">
                    {eid.slice(0, 8)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
