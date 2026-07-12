import apiClient from './client'

export interface MediaSearchItem {
  title: string
  source: 'youtube' | 'bilibili' | 'bt'
  url?: string
  magnet?: string
  duration?: number
  thumbnail?: string
  size?: string
  seeders?: number
}

export interface MovieSearchResponse {
  results: MediaSearchItem[]
  total: number
}

export async function searchMovie(keyword: string): Promise<MovieSearchResponse> {
  const { data } = await apiClient.post('/movie/movie', { keyword, sources: 'all' })
  return data
}
