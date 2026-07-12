export interface FormatInfo {
  format_id: string
  quality: string
  ext: string
  file_size?: number
  is_audio: boolean
  is_video: boolean
}

export interface ParseURLResponse {
  title: string
  platform: string
  media_type: string
  formats: FormatInfo[]
  thumbnail: string
  duration: number
}

export interface DownloadTask {
  id: string
  url: string
  platform: string
  title: string
  status: 'pending' | 'downloading' | 'completed' | 'failed'
  progress: number
  file_size: number
  error_message: string
  created_at: string
  completed_at?: string
}

export interface PlaylistItem {
  url: string
  title: string
  duration: number
  thumbnail: string
}

export interface PlaylistParseResponse {
  title: string
  platform: string
  items: PlaylistItem[]
}

export interface SearchResult {
  platform: string
  title: string
  artist: string
  url: string
  duration: number
  thumbnail: string
}

export interface MediaItem {
  id: string
  title: string
  artist: string
  album: string
  duration: number
  platform: string
  media_type: string
  file_path: string
  file_size: number
  cover_path: string
  bitrate: number
  resolution: string
  created_at: string
}
