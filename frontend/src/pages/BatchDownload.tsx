import { useState } from 'react'
import { Card, Input, Button, Space, Table, message } from 'antd'
import { parsePlaylist, batchDownload } from '../api/playlists'
import type { PlaylistItem } from '../types'

export default function BatchDownload() {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [playlistTitle, setPlaylistTitle] = useState('')
  const [items, setItems] = useState<PlaylistItem[]>([])
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const handleParse = async () => {
    if (!url.trim()) return
    setLoading(true)
    try {
      const result = await parsePlaylist(url.trim())
      setPlaylistTitle(result.title)
      setItems(result.items)
      setSelectedRowKeys(result.items.map((_, idx) => idx))
    } catch (e: any) {
      message.error('解析失败: ' + (e.response?.data?.detail || e.message))
    }
    setLoading(false)
  }

  const handleBatchDownload = async () => {
    const selectedItems = selectedRowKeys.map((key) => items[Number(key)])
    try {
      await batchDownload(
        selectedItems.map((item) => ({
          url: item.url,
          platform: item.url.includes('163.com') ? 'netease' :
                    item.url.includes('y.qq.com') ? 'qqmusic' :
                    item.url.includes('spotify.com') ? 'spotify' :
                    item.url.includes('youtube.com') || item.url.includes('youtu.be') ? 'youtube' :
                    item.url.includes('bilibili.com') ? 'bilibili' : 'auto',
          format_id: 'bestaudio',
          title: item.title,
          media_type: 'music',
        }))
      )
      message.success(`已创建 ${selectedItems.length} 个下载任务`)
    } catch (e: any) {
      message.error('批量下载失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const columns = [
    { title: '标题', dataIndex: 'title', key: 'title' },
    {
      title: '时长', dataIndex: 'duration', key: 'duration',
      render: (d: number) => `${Math.floor(d / 60)}:${String(d % 60).padStart(2, '0')}`,
    },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card>
        <Input.Search
          placeholder="粘贴歌单链接（网易云/QQ音乐/Spotify）..."
          enterButton="解析歌单"
          loading={loading}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onSearch={handleParse}
        />
      </Card>
      {items.length > 0 && (
        <Card title={playlistTitle}>
          <Button
            type="primary"
            onClick={handleBatchDownload}
            disabled={selectedRowKeys.length === 0}
            style={{ marginBottom: 16 }}
          >
            下载选中 ({selectedRowKeys.length} 首)
          </Button>
          <Table
            rowKey={(_, idx) => String(idx!)}
            rowSelection={{
              selectedRowKeys,
              onChange: (keys) => setSelectedRowKeys(keys),
            }}
            columns={columns}
            dataSource={items}
            pagination={false}
            size="small"
          />
        </Card>
      )}
    </Space>
  )
}
