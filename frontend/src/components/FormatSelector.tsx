import { Card, Radio, Button, Space, Tag } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { ParseURLResponse } from '../types'

interface Props {
  parseResult: ParseURLResponse
  selectedFormat: string
  onFormatChange: (id: string) => void
  onDownload: () => void
}

export default function FormatSelector({ parseResult, selectedFormat, onFormatChange, onDownload }: Props) {
  return (
    <Card title={parseResult.title} size="small">
      <p>
        <Tag>{parseResult.platform}</Tag>
        <Tag>{parseResult.media_type === 'music' ? '音乐' : parseResult.media_type === 'live_photo' ? '动态照片' : '视频'}</Tag>
        {parseResult.duration > 0 && <Tag>{(parseResult.duration / 60).toFixed(1)} 分钟</Tag>}
      </p>
      <Radio.Group value={selectedFormat} onChange={(e) => onFormatChange(e.target.value)}>
        <Space direction="vertical">
          {parseResult.formats.map((fmt) => (
            <Radio key={fmt.format_id} value={fmt.format_id}>
              {fmt.quality}
              {fmt.file_size ? ` (${(fmt.file_size / 1024 / 1024).toFixed(1)} MB)` : ''}
            </Radio>
          ))}
        </Space>
      </Radio.Group>
      <div style={{ marginTop: 16 }}>
        <Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>
          下载
        </Button>
      </div>
    </Card>
  )
}
