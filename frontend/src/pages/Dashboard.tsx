import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic } from 'antd'
import { DownloadOutlined, CheckCircleOutlined, PlaySquareOutlined } from '@ant-design/icons'
import { listDownloads } from '../api/downloads'
import { listMedia } from '../api/media'

export default function Dashboard() {
  const [stats, setStats] = useState({ pending: 0, downloading: 0, completed: 0, totalMedia: 0 })

  useEffect(() => {
    Promise.all([
      listDownloads({ status: 'pending', size: 1 }),
      listDownloads({ status: 'downloading', size: 1 }),
      listDownloads({ status: 'completed', size: 1 }),
      listMedia({ size: 1 }),
    ]).then(([p, d, c, m]) => {
      setStats({
        pending: p.total,
        downloading: d.total,
        completed: c.total,
        totalMedia: m.total,
      })
    })
  }, [])

  return (
    <Row gutter={16}>
      <Col span={6}>
        <Card><Statistic title="等待中" value={stats.pending} prefix={<DownloadOutlined />} /></Card>
      </Col>
      <Col span={6}>
        <Card><Statistic title="下载中" value={stats.downloading} prefix={<DownloadOutlined />} valueStyle={{ color: '#1890ff' }} /></Card>
      </Col>
      <Col span={6}>
        <Card><Statistic title="已完成" value={stats.completed} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
      </Col>
      <Col span={6}>
        <Card><Statistic title="媒体库" value={stats.totalMedia} prefix={<PlaySquareOutlined />} valueStyle={{ color: '#722ed1' }} /></Card>
      </Col>
    </Row>
  )
}
