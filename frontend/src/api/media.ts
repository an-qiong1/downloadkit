import apiClient from './client'
import type { MediaItem } from '../types'

export async function listMedia(params?: {
  page?: number
  size?: number
  platform?: string
  media_type?: string
  search?: string
}): Promise<{ items: MediaItem[]; total: number }> {
  const { data } = await apiClient.get('/media', { params })
  return data
}

export async function deleteMedia(id: string): Promise<void> {
  await apiClient.delete(`/media/${id}`)
}

export function getStreamUrl(id: string): string {
  return `/api/media/${id}/stream`
}
