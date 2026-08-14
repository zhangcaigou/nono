import type { DeepSeekConstraintResult } from '@/types'

export const deepSeekConstraintGroups = [
  { status: 'satisfied', label: '满足的条件', className: 'border-emerald-100 bg-emerald-50 text-emerald-800' },
  { status: 'partially_satisfied', label: '部分满足的条件', className: 'border-amber-100 bg-amber-50 text-amber-800' },
  { status: 'violated', label: '明确违反的条件', className: 'border-red-100 bg-red-50 text-red-800' },
  { status: 'unknown', label: '无法确认的条件', className: 'border-gray-200 bg-gray-50 text-gray-600' },
] as const

export function groupDeepSeekResults(results: DeepSeekConstraintResult[]) {
  return deepSeekConstraintGroups.map((group) => ({
    ...group,
    items: results.filter((item) => item.status === group.status),
  }))
}
