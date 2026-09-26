import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Button, Input, Space, Modal, message,
  Typography, Tag, Tooltip, Popconfirm, Empty, Spin,
  Descriptions, List,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, DownloadOutlined,
  EditOutlined, DeleteOutlined, UnorderedListOutlined,
  SoundOutlined,
} from '@ant-design/icons'
import {
  listCollections, createCollection, deleteCollection,
  updateCollection, refreshCollection, getCollection,
} from '../api/collections'
import { batchDownload } from '../api/playlists'
import type { CollectionItem, CollectionDetail, CollectionTrack } from '../types'

const { Text, Title } = Typography

/** 平台标签颜色 */
const PLATFORM_COLORS: Record<string, string> = {
  netease: 'red',
  qqmusic: 'blue',
  spotify: 'green',
}

const PLATFORM_LABELS: Record<string, string> = {
  netease: '网易云',
  qqmusic: 'QQ音乐',
  spotify: 'Spotify',
}

export default function MyPlaylists() {
  // ── 状态 ──
  const [collections, setCollections] = useState<CollectionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshingIds, setRefreshingIds] = useState<Set<number>>(new Set())
  const [downloadingIds, setDownloadingIds] = useState<Set<number>>(new Set())

  // 添加弹窗
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addUrl, setAddUrl] = useState('')
  const [adding, setAdding] = useState(false)

  // 详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detail, setDetail] = useState<CollectionDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // 重命名弹窗
  const [renameModalOpen, setRenameModalOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<CollectionItem | null>(null)
  const [renameName, setRenameName] = useState('')
  const [renaming, setRenaming] = useState(false)

  // ── 加载列表 ──
  const fetchCollections = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listCollections()
      setCollections(data)
    } catch (e: any) {
      message.error('加载收藏列表失败: ' + (e.response?.data?.detail || e.message))
    }
    setLoading(false)
  }, [])

  useEffect(() => { fetchCollections() }, [fetchCollections])

  // ── 添加收藏 ──
  const handleAdd = async () => {
    if (!addUrl.trim()) return
    setAdding(true)
    try {
      await createCollection(addUrl.trim())
      message.success('收藏成功')
      setAddModalOpen(false)
      setAddUrl('')
      fetchCollections()
    } catch (e: any) {
      message.error('收藏失败: ' + (e.response?.data?.detail || e.message))
    }
    setAdding(false)
  }

  // ── 删除收藏 ──
  const handleDelete = async (id: number) => {
    try {
      await deleteCollection(id)
      message.success('已删除')
      fetchCollections()
    } catch (e: any) {
      message.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  // ── 刷新歌单 ──
  const handleRefresh = async (id: number) => {
    setRefreshingIds(prev => new Set(prev).add(id))
    try {
      const result = await refreshCollection(id)
      message.success(result.message || '刷新成功')
      fetchCollections()
    } catch (e: any) {
      message.error('刷新失败: ' + (e.response?.data?.detail || e.message))
    }
    setRefreshingIds(prev => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  // ── 查看详情 ──
  const handleViewDetail = async (id: number) => {
    setDetailOpen(true)
    setDetailLoading(true)
    try {
      const data = await getCollection(id)
      setDetail(data)
    } catch (e: any) {
      message.error('加载失败: ' + (e.response?.data?.detail || e.message))
      setDetailOpen(false)
    }
    setDetailLoading(false)
  }

  // ── 下载歌单全部歌曲 ──
  const handleDownloadAll = async (id: number) => {
    setDownloadingIds(prev => new Set(prev).add(id))
    try {
      const data = await getCollection(id)
      if (!data.tracks || data.tracks.length === 0) {
        message.warning('歌单中没有歌曲，请先刷新')
        return
      }

      // 复用现有批量下载接口
      const items = data.tracks.map((t: CollectionTrack) => ({
        url: buildSongUrl(t.platform, t.song_id),
        platform: t.platform,
        format_id: 'bestaudio',
        title: `${t.artist} - ${t.title}`,
        media_type: 'music' as const,
      }))
      await batchDownload(items)
      message.success(`已提交 ${items.length} 首歌曲下载任务`)
    } catch (e: any) {
      message.error('下载失败: ' + (e.response?.data?.detail || e.message))
    }
    setDownloadingIds(prev => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  // ── 重命名 ──
  const handleRename = async () => {
    if (!renameTarget || !renameName.trim()) return
    setRenaming(true)
    try {
      await updateCollection(renameTarget.id, { name: renameName.trim() })
      message.success('已重命名')
      setRenameModalOpen(false)
      setRenameTarget(null)
      fetchCollections()
    } catch (e: any) {
      message.error('重命名失败: ' + (e.response?.data?.detail || e.message))
    }
    setRenaming(false)
  }

  // 列定义
  const columns = [
    {
      title: '歌单名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: CollectionItem) => (
        <a onClick={() => handleViewDetail(record.id)}>
          <SoundOutlined style={{ marginRight: 6, color: '#1677ff' }} />
          {name}
        </a>
      ),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (p: string) => (
        <Tag color={PLATFORM_COLORS[p] || 'default'}>
          {PLATFORM_LABELS[p] || p}
        </Tag>
      ),
    },
    {
      title: '歌曲数',
      dataIndex: 'song_count',
      key: 'song_count',
      width: 80,
      align: 'center' as const,
    },
    {
      title: '上次刷新',
      dataIndex: 'refreshed_at',
      key: 'refreshed_at',
      width: 180,
      render: (t: string | null) => t || <Text type="secondary">未刷新</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: any, record: CollectionItem) => (
        <Space size="small">
          <Tooltip title="刷新歌单">
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={refreshingIds.has(record.id)}
              onClick={() => handleRefresh(record.id)}
            />
          </Tooltip>
          <Tooltip title="下载全部">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              loading={downloadingIds.has(record.id)}
              onClick={() => handleDownloadAll(record.id)}
            />
          </Tooltip>
          <Tooltip title="重命名">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setRenameTarget(record)
                setRenameName(record.name)
                setRenameModalOpen(true)
              }}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除这个收藏歌单？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* ── 页面标题 + 添加按钮 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <UnorderedListOutlined style={{ marginRight: 8 }} />
          我的歌单
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>
          添加收藏
        </Button>
      </div>

      {/* ── 歌单列表 ── */}
      <Card>
        <Table
          rowKey="id"
          dataSource={collections}
          columns={columns}
          loading={loading}
          pagination={false}
          locale={{ emptyText: <Empty description="还没有收藏的歌单，点击右上角添加" /> }}
        />
      </Card>

      {/* ── 添加弹窗 ── */}
      <Modal
        title="添加收藏歌单"
        open={addModalOpen}
        onOk={handleAdd}
        onCancel={() => { setAddModalOpen(false); setAddUrl('') }}
        confirmLoading={adding}
        okText="添加"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary">粘贴歌单链接，系统将自动解析并获取名称</Text>
          <Input
            placeholder="例如: https://music.163.com/playlist?id=123456789"
            value={addUrl}
            onChange={e => setAddUrl(e.target.value)}
            onPressEnter={handleAdd}
          />
        </Space>
      </Modal>

      {/* ── 重命名弹窗 ── */}
      <Modal
        title="重命名歌单"
        open={renameModalOpen}
        onOk={handleRename}
        onCancel={() => { setRenameModalOpen(false); setRenameTarget(null) }}
        confirmLoading={renaming}
        okText="确定"
        cancelText="取消"
      >
        <Input
          value={renameName}
          onChange={e => setRenameName(e.target.value)}
          onPressEnter={handleRename}
        />
      </Modal>

      {/* ── 歌单详情弹窗 ── */}
      <Modal
        title={detail?.name || '歌单详情'}
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setDetail(null) }}
        footer={
          detail ? (
            <Space>
              <Button
                icon={<ReloadOutlined />}
                loading={refreshingIds.has(detail.id)}
                onClick={() => {
                  handleRefresh(detail.id)
                  handleViewDetail(detail.id)
                }}
              >
                刷新
              </Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={downloadingIds.has(detail.id)}
                onClick={() => handleDownloadAll(detail.id)}
              >
                下载全部 ({detail.tracks.length} 首)
              </Button>
            </Space>
          ) : null
        }
        width={700}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : detail ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* 歌单信息 */}
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="平台">
                <Tag color={PLATFORM_COLORS[detail.platform] || 'default'}>
                  {PLATFORM_LABELS[detail.platform] || detail.platform}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="歌曲数">{detail.song_count}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{detail.created_at}</Descriptions.Item>
              <Descriptions.Item label="上次刷新">
                {detail.refreshed_at || <Text type="secondary">未刷新</Text>}
              </Descriptions.Item>
            </Descriptions>

            {/* 歌曲列表 */}
            <Text strong>歌曲列表 ({detail.tracks.length} 首)</Text>
            <List
              size="small"
              bordered
              dataSource={detail.tracks}
              renderItem={(track, idx) => (
                <List.Item>
                  <Text>
                    {idx + 1}. {track.title}
                    {track.artist ? <Text type="secondary"> — {track.artist}</Text> : null}
                  </Text>
                </List.Item>
              )}
              locale={{ emptyText: <Empty description="暂无歌曲" /> }}
              style={{ maxHeight: 400, overflow: 'auto' }}
            />
          </Space>
        ) : null}
      </Modal>
    </div>
  )
}

/** 根据平台和 song_id 构建单曲链接 */
function buildSongUrl(platform: string, songId: string): string {
  switch (platform) {
    case 'netease':
      return `https://music.163.com/song?id=${songId}`
    case 'qqmusic':
      return `https://y.qq.com/n/ryqq/songDetail/${songId}`
    default:
      return ''
  }
}
