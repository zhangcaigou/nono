import apiClient from './client'
import {
  HealthResponse,
  CreateSearchTaskRequest,
  SearchTaskAccepted,
  SearchTask,
  SearchResult,
  RecommendationTrace,
} from '@/types'

// 健康检查
export const getHealth = () =>
  apiClient.get<HealthResponse>('/api/v1/health').then((res) => res.data)

// 创建搜索任务
export const createSearchTask = (data: CreateSearchTaskRequest) =>
  apiClient.post<SearchTaskAccepted>('/api/v1/search-tasks', data).then((res) => res.data)

// 查询任务状态
export const getTask = (taskId: string) =>
  apiClient.get<SearchTask>(`/api/v1/search-tasks/${taskId}`).then((res) => res.data)

// 获取任务结果
export const getTaskResult = (taskId: string) =>
  apiClient.get<SearchResult>(`/api/v1/search-tasks/${taskId}/result`).then((res) => res.data)

// 取消任务
export const cancelTask = (taskId: string) =>
  apiClient.delete<SearchTask>(`/api/v1/search-tasks/${taskId}`).then((res) => res.data)

// 获取单篇论文的追溯详情（仅在用户点击"加载全文证据"时调用）
export const getPaperTrace = (taskId: string, paperId: string, includeFulltext = false) =>
  apiClient
    .get<RecommendationTrace>(
      `/api/v1/search-tasks/${taskId}/papers/${encodeURIComponent(paperId)}/trace`,
      { params: { include_fulltext: includeFulltext } }
    )
    .then((res) => res.data)