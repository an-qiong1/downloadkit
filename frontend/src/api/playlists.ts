import apiClient from './client'
import type { PlaylistParseResponse, DownloadTask } from '../types'

export async function parsePlaylist(url: string): Promise<PlaylistParseResponse> {
  const { data } = await apiClient.post('/playlists/parse', { url })
  return data
}

export async function batchDownload(items: {
  url: string
  platform: string
  format_id: string
  title: string
  media_type: string
}[]): Promise<DownloadTask[]> {
  const { data } = await apiClient.post('/playlists/batch-download', { items })
  return data
}
