import apiClient from './client'
import type { ParseURLResponse, DownloadTask } from '../types'

export async function parseURL(url: string): Promise<ParseURLResponse> {
  const { data } = await apiClient.post('/downloads/parse', { url })
  return data
}

export async function createDownload(params: {
  url: string
  platform: string
  format_id: string
  title: string
  media_type: string
}): Promise<DownloadTask> {
  const { data } = await apiClient.post('/downloads/create', params)
  return data
}

export async function listDownloads(params?: {
  page?: number
  size?: number
  status?: string
}): Promise<{ items: DownloadTask[]; total: number }> {
  const { data } = await apiClient.get('/downloads', { params })
  return data
}

export async function getDownload(id: string): Promise<DownloadTask> {
  const { data } = await apiClient.get(`/downloads/${id}`)
  return data
}

export async function cancelDownload(id: string): Promise<void> {
  await apiClient.post(`/downloads/${id}/cancel`)
}

export async function retryDownload(id: string): Promise<DownloadTask> {
  const { data } = await apiClient.post(`/downloads/${id}/retry`)
  return data
}

export async function deleteDownload(id: string): Promise<void> {
  await apiClient.delete(`/downloads/${id}`)
}

export async function batchDeleteDownloads(ids: string[]): Promise<void> {
  await apiClient.post('/downloads/batch-delete', ids)
}
