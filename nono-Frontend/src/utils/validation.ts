// 查询文本校验
export const validateQuery = (query: string): { valid: boolean; message?: string } => {
  const trimmed = query.trim()
  if (trimmed.length === 0) {
    return { valid: false, message: '请输入学术检索问题' }
  }
  if (trimmed.length < 3) {
    return { valid: false, message: '检索问题至少需要 3 个字符' }
  }
  if (trimmed.length > 2000) {
    return { valid: false, message: '检索问题不能超过 2000 个字符' }
  }
  return { valid: true }
}