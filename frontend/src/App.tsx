import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout, Menu, theme } from 'antd'
import {
  DashboardOutlined,
  DownloadOutlined,
  UnorderedListOutlined,
  PlaySquareOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import DownloadCenter from './pages/DownloadCenter'
import BatchDownload from './pages/BatchDownload'
import MyPlaylists from './pages/MyPlaylists'
import TaskManager from './pages/TaskManager'
import MediaLibrary from './pages/MediaLibrary'
import Settings from './pages/Settings'

const { Sider, Content } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/download', icon: <DownloadOutlined />, label: '下载中心' },
  { key: '/download/batch', icon: <DownloadOutlined />, label: '批量下载' },
  { key: '/collections', icon: <UnorderedListOutlined />, label: '我的歌单' },
  { key: '/tasks', icon: <UnorderedListOutlined />, label: '下载管理' },
  { key: '/library', icon: <PlaySquareOutlined />, label: '媒体库' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const { token: { colorBgContainer } } = theme.useToken()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider>
        <div style={{
          height: 48, margin: 16, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontWeight: 'bold', fontSize: 18
        }}>
          Media Fetch
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Content style={{ margin: 24, padding: 24, background: colorBgContainer, borderRadius: 8 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/download" element={<DownloadCenter />} />
            <Route path="/download/batch" element={<BatchDownload />} />
            <Route path="/collections" element={<MyPlaylists />} />
            <Route path="/tasks" element={<TaskManager />} />
            <Route path="/library" element={<MediaLibrary />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export default App
