import { describe, expect, it } from 'vitest'
import { validateQuery } from './validation'

describe('validateQuery', () => {
  it('rejects empty, short, and oversized queries', () => {
    expect(validateQuery('   ').valid).toBe(false)
    expect(validateQuery('ab').valid).toBe(false)
    expect(validateQuery('x'.repeat(2001)).valid).toBe(false)
  })

  it('accepts a trimmed academic query within the contract limit', () => {
    expect(validateQuery('  transformer 检索  ')).toEqual({ valid: true })
  })
})
