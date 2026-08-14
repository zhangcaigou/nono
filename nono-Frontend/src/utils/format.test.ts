import { describe, expect, it } from 'vitest'
import { calcDuration, formatElapsedDuration, scoreToPercent, stageToChinese } from './format'

describe('format utilities', () => {
  it('maps public backend stages and relevance scores', () => {
    expect(stageToChinese('searching')).toBe('正在搜索论文')
    expect(scoreToPercent(0.856)).toBe('86%')
  })

  it('formats short and minute-level task duration', () => {
    expect(calcDuration('2026-08-03T00:00:00Z', '2026-08-03T00:00:42Z')).toBe('42 秒')
    expect(calcDuration('2026-08-03T00:00:00Z', '2026-08-03T00:01:05Z')).toBe('1 分 5 秒')
    expect(calcDuration('2026-08-03T00:02:00Z', '2026-08-03T00:00:00Z')).toBe('0 秒')
    expect(formatElapsedDuration(1_999)).toBe('1 秒')
  })
})
