import { useState } from 'react'
import { Card, Input, Button, Space, Tag, Table, message, Tabs } from 'antd'
import { SearchOutlined, DownloadOutlined, LinkOutlined } from '@ant-design/icons'
import { searchMovie, type MediaSearchItem } from '../api/movieSearch'
import { createDownload } from '../api/downloads'

export default function MovieSearch() {
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<MediaSearchItem[]>([])
  const [activeTab, setActiveTab] = useState('all')

  const handleSearch = async () => {
    if (!keyword.trim()) return
    setLoading(true)
    try {
      const data = await searchMovie(keyword.trim())
      setResults(data.results)
      if (data.results.length === 0) {
        message.info('未找到相关资源')
      }
    } catch (e: any) {
      message.error('搜索失败: ' + (e.response?.data?.detail || e.message))
    }
    setLoading(false)
  }

  const handleDownload = async (item: MediaSearchItem) => {
    try {
      if (item.source === 'bt') {
        // BT资源通过磁力链接下载
        message.loading({ content: '正在下载磁力链接...', key: item.magnet })
        // 调用磁力下载
        await createDownload({
          url: item.magnet || '',
          platform: 'bt',
          format_id: 'magnet',
          title: item.title,
          media_type: 'video',
        })
        message.success({ content: '下载任务已创建', key: item.magnet })
      } else {
        // YouTube/Bilibili 通过 yt-dlp 下载
        await createDownload({
          url: item.url || '',
          platform: item.source,
          format_id: 'best',
          title: item.title,
          media_type: 'video',
        })
        message.success('下载任务已创建')
      }
    } catch (e: any) {
      message.error('下载失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const sourceColors: Record<string, string> = {
    youtube: 'red',
    bilibili: 'pink',
    bt: 'green',
  }
  const sourceNames: Record<string, string> = {
    youtube: 'YouTube',
    bilibili: 'Bilibili',
    bt: 'BT磁力',
  }

  const filteredResults = activeTab === 'all'
    ? results
    : results.filter(r => r.source === activeTab)

  const columns = [
    {
      title: '来源', dataIndex: 'source', key: 'source', width: 100,
      render: (s: string) => <Tag color={sourceColors[s]}>{sourceNames[s] || s}</Tag>,
    },
    {
      title: '标题', dataIndex: 'title', key: 'title', ellipsis: true,
    },
    {
      title: '大小/时长', key: 'info', width: 120,
      render: (_: any, r: MediaSearchItem) =>
        r.size || (r.duration ? `${Math.floor(r.duration / 60)}:${String(r.duration % 60).padStart(2, '0')}` : '-'),
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: any, r: MediaSearchItem) => (
        <Button
          type="primary"
          size="small"
          icon={r.source === 'bt' ? <LinkOutlined /> : <DownloadOutlined />}
          onClick={() => handleDownload(r)}
        >
          {r.source === 'bt' ? '磁力下载' : '下载'}
        </Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* 搜索栏 */}
      <Card>
        <Input.Search
          placeholder="输入影视名称，全网搜索高清资源..."
          enterButton={<><SearchOutlined /> 全网搜索</>}
          size="large"
          loading={loading}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={handleSearch}
        />
      </Card>

      {/* 统计信息 */}
      {results.length > 0 && (
        <Card size="small">
          <Space>
            <span>共找到 <strong>{results.length}</strong> 个资源</span>
            {results.filter(r => r.source === 'youtube').length > 0 && (
              <Tag color="red">YouTube {results.filter(r => r.source === 'youtube').length}</Tag>
            )}
            {results.filter(r => r.source === 'bilibili').length > 0 && (
              <Tag color="pink">Bilibili {results.filter(r => r.source === 'bilibili').length}</Tag>
            )}
            {results.filter(r => r.source === 'bt').length > 0 && (
              <Tag color="green">BT磁力 {results.filter(r => r.source === 'bt').length}</Tag>
            )}
          </Space>
        </Card>
      )}

      {/* 搜索结果 */}
      {results.length > 0 && (
        <Card>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              { key: 'all', label: `全部 (${results.length})` },
              { key: 'youtube', label: `YouTube (${results.filter(r => r.source === 'youtube').length})` },
              { key: 'bilibili', label: `Bilibili (${results.filter(r => r.source === 'bilibili').length})` },
              { key: 'bt', label: `BT磁力 (${results.filter(r => r.source === 'bt').length})` },
            ]}
          />
          <Table
            rowKey={(_, idx) => String(idx!)}
            columns={columns}
            dataSource={filteredResults}
            pagination={{ pageSize: 20 }}
            size="small"
          />
        </Card>
      )}
    </Space>
  )
}
