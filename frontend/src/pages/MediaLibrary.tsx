import { useState, useEffect } from 'react'
import { Row, Col, Card, Input, Select, Pagination, Tag, Space, Popconfirm, message } from 'antd'
import { DeleteOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { listMedia, deleteMedia, getStreamUrl } from '../api/media'
import type { MediaItem } from '../types'

export default function MediaLibrary() {
  const [items, setItems] = useState<MediaItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [platform, setPlatform] = useState('')
  const [mediaType, setMediaType] = useState('')
  const [loading, setLoading] = useState(false)

  const fetch = async () => {
    setLoading(true)
    const r = await listMedia({ page, size: 20, platform, media_type: mediaType, search })
    setItems(r.items)
    setTotal(r.total)
    setLoading(false)
  }

  useEffect(() => { fetch() }, [page, platform, mediaType, search])

  const handleDelete = async (id: string) => {
    await deleteMedia(id)
    message.success('已删除')
    fetch()
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%' }}>
        <Input.Search
          placeholder="搜索标题..."
          onSearch={(v) => { setSearch(v); setPage(1) }}
          style={{ width: 300 }}
          allowClear
        />
        <Select
          placeholder="平台筛选"
          allowClear
          style={{ width: 150 }}
          onChange={(v) => { setPlatform(v || ''); setPage(1) }}
          options={[
            { value: 'netease', label: '网易云音乐' },
            { value: 'qqmusic', label: 'QQ音乐' },
            { value: 'spotify', label: 'Spotify' },
            { value: 'douyin', label: '抖音' },
            { value: 'youtube', label: 'YouTube' },
            { value: 'bilibili', label: 'Bilibili' },
          ]}
        />
        <Select
          placeholder="类型"
          allowClear
          style={{ width: 120 }}
          onChange={(v) => { setMediaType(v || ''); setPage(1) }}
          options={[
            { value: 'music', label: '音乐' },
            { value: 'video', label: '视频' },
            { value: 'live_photo', label: '动态照片' },
          ]}
        />
      </Space>
      <Row gutter={[16, 16]}>
        {items.map((item) => (
          <Col key={item.id} xs={24} sm={12} md={8} lg={6}>
            <Card
              hoverable
              loading={loading}
              cover={
                <div style={{
                  height: 180, background: '#f0f0f0',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 48
                }}>
                  {item.media_type === 'music' ? '🎵' : '🎬'}
                </div>
              }
              actions={[
                <PlayCircleOutlined key="play" onClick={() => window.open(getStreamUrl(item.id), '_blank')} />,
                <Popconfirm key="delete" title="确认删除？" onConfirm={() => handleDelete(item.id)}>
                  <DeleteOutlined />
                </Popconfirm>,
              ]}
            >
              <Card.Meta
                title={<div style={{ fontSize: 14 }}>{item.title}</div>}
                description={
                  <Space size={4} wrap>
                    <Tag>{item.platform}</Tag>
                    {item.artist && <span>{item.artist}</span>}
                  </Space>
                }
              />
            </Card>
          </Col>
        ))}
      </Row>
      <div style={{ marginTop: 16, textAlign: 'center' }}>
        <Pagination current={page} total={total} pageSize={20} onChange={setPage} />
      </div>
    </div>
  )
}
