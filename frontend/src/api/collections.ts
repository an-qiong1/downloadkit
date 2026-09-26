import apiClient from './client'
import type { CollectionItem, CollectionDetail, RefreshResponse } from '../types'

export async function listCollections(): Promise<CollectionItem[]> {
  const { data } = await apiClient.get('/collections')
  return data
}

export async function createCollection(url: string, name?: string): Promise<CollectionDetail> {
  const { data } = await apiClient.post('/collections', { url, name: name ?? '' })
  return data
}

export async function getCollection(id: number): Promise<CollectionDetail> {
  const { data } = await apiClient.get(`/collections/${id}`)
  return data
}

export async function updateCollection(id: number, payload: { name?: string }): Promise<CollectionDetail> {
  const { data } = await apiClient.put(`/collections/${id}`, payload)
  return data
}

export async function deleteCollection(id: number): Promise<void> {
  await apiClient.delete(`/collections/${id}`)
}

export async function refreshCollection(id: number): Promise<RefreshResponse> {
  const { data } = await apiClient.post(`/collections/${id}/refresh`)
  return data
}
