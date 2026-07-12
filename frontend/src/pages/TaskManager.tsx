import { useState, useEffect, useCallback } from 'react'
import { Table, Tag, Button, Space, Progress, message, Modal } from 'antd'
import { ReloadOutlined, CloseOutlined, DeleteOutlined } from '@ant-design/icons'
import { listDownloads, cancelDownload, retryDownload, deleteDownload, batchDeleteDownloads } from '../api/downloads'
import type { DownloadTask } from '../types'
import { useWebSocket } from '../hooks/useWebSocket'

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  downloading: { color: 'processing', text: '下载中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
}

export default function TaskManager() {
  const [tasks, setTasks] = useState<DownloadTask[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [wsTaskId, setWsTaskId] = useState<string | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])

  const fetchTasks = async () => {
    setLoading(true)
    const result = await listDownloads({ page, size: 20 })
    setTasks(result.items)
    setTotal(result.total)
    setLoading(false)
  }

  useEffect(() => { fetchTasks() }, [page])

  useEffect(() => {
    const downloading = tasks.find(t => t.status === 'downloading')
    setWsTaskId(downloading?.id || null)
  }, [tasks])

  const handleWsMessage = useCallback((msg: any) => {
    setTasks(prev => prev.map(t =>
      t.id === msg.task_id ? { ...t, progress: msg.progress, status: msg.status } : t
    ))
  }, [])

  useWebSocket(wsTaskId, handleWsMessage)

  const handleCancel = async (id: string) => {
    await cancelDownload(id)
    message.success('已取消')
    fetchTasks()
  }

  const handleRetry = async (id: string) => {
    await retryDownload(id)
    message.success('已重试')
    fetchTasks()
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '删除后将同时移除关联的媒体库记录，确定要删除吗？',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await deleteDownload(id)
        message.success('已删除')
        setSelectedRowKeys(prev => prev.filter(k => k !== id))
        fetchTasks()
      },
    })
  }

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: `确认删除 ${selectedRowKeys.length} 个任务？`,
      content: '删除后将同时移除关联的媒体库记录，确定要删除吗？',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        await batchDeleteDownloads(selectedRowKeys)
        message.success(`已删除 ${selectedRowKeys.length} 个任务`)
        setSelectedRowKeys([])
        fetchTasks()
      },
    })
  }

  const columns = [
    {
      title: '标题', dataIndex: 'title', key: 'title', ellipsis: true,
    },
    { title: '平台', dataIndex: 'platform', key: 'platform', render: (p: string) => <Tag>{p}</Tag> },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => {
        const m = statusMap[s] || { color: 'default', text: s }
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: '进度', dataIndex: 'progress', key: 'progress',
      render: (p: number, r: DownloadTask) =>
        r.status === 'downloading' ? <Progress percent={Math.round(p)} size="small" /> : '-',
    },
      {
        title: '操作', key: 'action',
        render: (_: any, r: DownloadTask) => (
          <Space>
            {r.status === 'downloading' && (
              <Button size="small" icon={<CloseOutlined />} onClick={() => handleCancel(r.id)}>取消</Button>
            )}
            {r.status === 'failed' && (
              <Button size="small" icon={<ReloadOutlined />} onClick={() => handleRetry(r.id)}>重试</Button>
            )}
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
          </Space>
        ),
      },
  ]

  return (
    <>
      {selectedRowKeys.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <span style={{ marginRight: 8 }}>已选 {selectedRowKeys.length} 项</span>
          <Button danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>批量删除</Button>
        </div>
      )}
      <Table
        rowKey="id"
        columns={columns}
        dataSource={tasks}
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
        pagination={{ current: page, total, onChange: setPage, pageSize: 20 }}
      />
    </>
  )
}
