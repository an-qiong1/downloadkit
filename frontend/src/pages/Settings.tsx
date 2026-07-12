import { useState } from 'react'
import { Card, Form, Input, Button, InputNumber, message, Typography } from 'antd'

const { Title } = Typography

export default function Settings() {
  const [saving, setSaving] = useState(false)

  const handleSave = async (values: any) => {
    setSaving(true)
    await new Promise(r => setTimeout(r, 500))
    localStorage.setItem('media_fetch_settings', JSON.stringify(values))
    message.success('设置已保存（本地存储）')
    setSaving(false)
  }

  return (
    <div>
      <Title level={4}>平台配置</Title>
      <Card title="网易云音乐 Cookie" style={{ marginBottom: 16 }}>
        <Form layout="vertical" onFinish={handleSave}>
          <Form.Item label="Cookie（选填，可提升音质）" name="netease_cookie">
            <Input.TextArea rows={2} placeholder="网易云登录后的 Cookie，非必填" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
        </Form>
      </Card>
      <Card title="下载设置" style={{ marginBottom: 16 }}>
        <Form layout="vertical" onFinish={handleSave} initialValues={{ concurrent: 3, download_dir: 'D:\\Dowland\\media-fetch\\media' }}>
          <Form.Item label="并发下载数" name="concurrent">
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item label="下载目录" name="download_dir">
            <Input />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
        </Form>
      </Card>
    </div>
  )
}
