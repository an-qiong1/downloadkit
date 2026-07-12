import apiClient from './client'
import type { SearchResult } from '../types'

export async function searchMusic(keyword: string, platform: string = 'all'): Promise<SearchResult[]> {
  const { data } = await apiClient.post('/search', { keyword, platform })
  return data.results
}
