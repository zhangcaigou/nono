import { TaskStage } from '@/types'

// 阶段 -> 中文文案
export const stageToChinese = (stage: TaskStage): string => {
  const map: Record<TaskStage, string> = {
    queued: '等待执行',
    loading: '正在加载模型',
    searching: '正在搜索论文',
    enriching: '正在补全摘要与生成证据',
    finished: '搜索完成',
  }
  return map[stage] || stage
}

// 分数转百分比（保留整数）
export const scoreToPercent = (score: number): string => {
  return `${Math.round(score * 100)}%`
}

// 格式化 ISO 时间为本地可读
export const formatTime = (iso: string | null): string => {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

// 格式化非负耗时。运行中任务使用浏览器本地累加值，避免服务器与浏览器时钟偏差产生负数。
export const formatElapsedDuration = (milliseconds: number): string => {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (totalSeconds < 60) return `${totalSeconds} 秒`
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  return `${mins} 分 ${secs} 秒`
}

// 使用同一时钟来源的两个时间戳计算最终耗时
export const calcDuration = (start: string | null, end: string | null): string => {
  if (!start || !end) return '--'
  const startTime = new Date(start).getTime()
  const endTime = new Date(end).getTime()
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime)) return '--'
  return formatElapsedDuration(endTime - startTime)
}
