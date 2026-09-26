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

export interface CollectionTrack {
  id: number
  title: string
  artist: string
  album: string
  song_id: string
  platform: string
  sort_order: number
}

export interface CollectionItem {
  id: number
  name: string
  url: string
  platform: string
  song_count: number
  auto_name: boolean
  created_at: string
  refreshed_at: string | null
}

export interface CollectionDetail extends CollectionItem {
  tracks: CollectionTrack[]
}

export interface RefreshResponse {
  collection: CollectionDetail
  status: string
  message: string
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
