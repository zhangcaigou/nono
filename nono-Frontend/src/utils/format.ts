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

// 计算耗时（秒）
export const calcDuration = (start: string | null, end: string | null): string => {
  if (!start || !end) return '--'
  const diff = (new Date(end).getTime() - new Date(start).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)} 秒`
  const mins = Math.floor(diff / 60)
  const secs = Math.round(diff % 60)
  return `${mins} 分 ${secs} 秒`
}