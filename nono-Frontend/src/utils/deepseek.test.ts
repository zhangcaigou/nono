import { describe, expect, it } from 'vitest'
import { groupDeepSeekResults } from './deepseek'
import type { ConstraintStatus, DeepSeekConstraintResult } from '@/types'

describe('DeepSeek trace presentation', () => {
  it('groups and labels all four constraint states', () => {
    const statuses: ConstraintStatus[] = ['satisfied', 'partially_satisfied', 'violated', 'unknown']
    const results: DeepSeekConstraintResult[] = statuses.map((status, index) => ({
      constraint_id: `C${index + 1}`,
      status,
      explanation: status,
      evidence_ids: status === 'unknown' ? [] : [`E${index + 1}`],
      confidence: 0.9,
    }))

    const groups = groupDeepSeekResults(results)

    expect(groups.map((group) => group.label)).toEqual([
      '满足的条件', '部分满足的条件', '明确违反的条件', '无法确认的条件',
    ])
    expect(groups.map((group) => group.items[0].status)).toEqual(statuses)
  })
})
