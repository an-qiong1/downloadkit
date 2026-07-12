import { useState } from 'react'
import { Input, Button, Space, Card, message } from 'antd'
import { LinkOutlined, SearchOutlined } from '@ant-design/icons'
import { parseURL, createDownload } from '../api/downloads'
import { searchMusic } from '../api/search'
import FormatSelector from './FormatSelector'

export default function URLInput() {
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<'url' | 'search'>('url')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [parseResult, setParseResult] = useState<any>(null)
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [selectedFormat, setSelectedFormat] = useState<string>('')

  const handleParse = async () => {
    if (!url.trim()) return
    setLoading(true)
    try {
      const result = await parseURL(url.trim())
      setParseResult(result)
      setSelectedFormat(result.formats[0]?.format_id || '')
      setSearchResults([])
    } catch (e: any) {
      message.error('解析失败: ' + (e.response?.data?.detail || e.message))
    }
    setLoading(false)
  }

  const handleSearch = async () => {
    if (!keyword.trim()) return
    setLoading(true)
    try {
      const results = await searchMusic(keyword.trim())
      setSearchResults(results)
      setParseResult(null)
    } catch (e: any) {
      message.error('搜索失败: ' + (e.response?.data?.detail || e.message))
    }
    setLoading(false)
  }

  const handleDownload = async () => {
    if (!parseResult) return
    try {
      await createDownload({
        url: url.trim(),
        platform: parseResult.platform,
        format_id: selectedFormat,
        title: parseResult.title,
        media_type: parseResult.media_type,
      })
      message.success('下载任务已创建')
    } catch (e: any) {
      message.error('创建失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  const handleSearchDownload = async (item: any) => {
    try {
      await createDownload({
        url: item.url,
        platform: item.platform,
        format_id: 'bestaudio',
        title: `${item.artist} - ${item.title}`,
        media_type: 'music',
      })
      message.success('下载任务已创建')
    } catch (e: any) {
      message.error('失败: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <Card>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Space>
          <Button type={mode === 'url' ? 'primary' : 'default'} onClick={() => setMode('url')}>
            <LinkOutlined /> 链接下载
          </Button>
          <Button type={mode === 'search' ? 'primary' : 'default'} onClick={() => setMode('search')}>
            <SearchOutlined /> 搜索下载
          </Button>
        </Space>

        {mode === 'url' ? (
          <Input.Search
            placeholder="粘贴网易云/QQ音乐/Spotify/抖音链接..."
            enterButton="解析"
            loading={loading}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onSearch={handleParse}
          />
        ) : (
          <Input.Search
            placeholder="输入歌曲名或歌手..."
            enterButton="搜索"
            loading={loading}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={handleSearch}
          />
        )}

        {parseResult && (
          <FormatSelector
            parseResult={parseResult}
            selectedFormat={selectedFormat}
            onFormatChange={setSelectedFormat}
            onDownload={handleDownload}
          />
        )}

        {searchResults.map((item, idx) => (
          <Card key={idx} size="small">
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <div>
                <strong>{item.artist}</strong> - {item.title}
                <span style={{ marginLeft: 8, color: '#999' }}>[{item.platform}]</span>
              </div>
              <Button size="small" type="primary" onClick={() => handleSearchDownload(item)}>
                下载
              </Button>
            </Space>
          </Card>
        ))}
      </Space>
    </Card>
  )
}
