# DownloadKit 开发指南

## 开发环境搭建

### 系统要求
- Python 3.10+
- Node.js 16+（可选，用于前端开发）
- FFmpeg（可选，用于B站视频合并）

### 安装步骤

```bash
# 克隆仓库
git clone <repo-url>
cd downloadkit

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 安装依赖（开发模式）
pip install -e ".[dev]"

# 安装可选依赖
pip install -e ".[media]"  # 实况照片功能
pip install -e ".[browser]"  # 浏览器解析功能
pip install -e ".[douyin]"  # 抖音签名功能
```

### 验证安装

```bash
# 检查Python版本
python --version

# 检查依赖
pip list | grep downloadkit

# 运行测试
pytest -q
```

## 项目结构

```
downloadkit/
├── downloadkit/              # 主包
│   ├── __init__.py          # 包初始化
│   ├── cli.py               # CLI 入口（click + rich）
│   ├── server.py            # Web 后端（FastAPI，64 条路由）
│   ├── searcher.py          # 聚合搜索
│   ├── downloader.py        # 下载引擎
│   ├── video_service.py     # 视频平台分发共享层（server 与 CLI 共用）
│   ├── playlist.py          # 歌单解析
│   ├── collection.py        # 收藏歌单（SQLite 持久化）
│   ├── download_queue.py    # 下载队列
│   ├── subscription.py      # 创作者订阅数据模型
│   ├── subscription_service.py  # 订阅业务（预览、单查、补下）
│   ├── poller.py            # 定时检查（间隔/每天时刻 + 抖动 + 退避）
│   ├── history.py           # 下载历史（SQLite）
│   ├── bookmarks.py         # 书签导入与解析
│   ├── sniffer.py           # 资源嗅探（L2 深度抓取）
│   ├── episodes.py          # 播放页选集展开
│   ├── stream_filter.py     # 选流过滤
│   ├── tagger.py            # 音频标签写入
│   ├── enricher.py          # 元数据补充
│   ├── motion_photo.py      # 实况照片生成
│   ├── file_manager.py      # 路径安全
│   ├── proxy.py             # 代理三态与平台覆盖
│   ├── browser_cookie.py    # 浏览器 Cookie
│   ├── exceptions.py        # 自定义异常
│   ├── utils.py             # 工具函数
│   ├── logger.py            # 日志配置
│   ├── douyin.py            # 抖音解析（API / 浏览器 / 图文 / 实况）
│   ├── douyin_browser.py    # 抖音浏览器后端（扫码登录、订阅抓取）
│   ├── douyin_third_party.py  # 抖音第三方解析
│   ├── platforms/           # 音乐平台适配
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── netease.py
│   │   ├── qqmusic.py
│   │   ├── itzo.py
│   │   ├── gequbao.py
│   │   └── migu.py
│   ├── bilibili.py / youtube.py / xiaohongshu.py / generic_video.py  # 视频平台
│   └── static/              # Web 前端（手写 HTML/CSS/JS，主线用）
│       ├── index.html
│       ├── css/
│       ├── js/
│       └── vendor/
├── tests/                   # 测试用例（1006 passed / 6 skipped）
├── docs/                    # 使用说明、验证与优化报告
├── build/                   # 打包与验收脚本（build-release.ps1、test-exe-*）
├── backend/ frontend/       # NAS 多容器版（FastAPI+Celery+Redis / React+AntD）
├── run.py                   # 启动脚本
├── server.py                # 桌面版 Web 后端入口
├── pyproject.toml           # 项目配置
├── docker-compose.yml       # 单容器 Docker
├── docker-compose.prod.yml  # 生产 Docker
├── docker-compose.nas.yml   # NAS 多容器 Docker
├── Dockerfile               # 容器镜像
├── music-dl.cmd             # Windows 快捷启动
├── start.bat                # Windows 启动脚本
├── check_types.py           # 类型检查脚本
├── PLAN.md                  # 当前开发计划与进度（交接文档）
├── PLAN-资源嗅探批量下载.md  # 资源嗅探专项计划
├── README.md                # 项目说明
├── ARCHITECTURE.md          # 架构与三套部署形态判别
├── CHANGELOG.md             # 更新日志
└── DEVELOPMENT.md           # 开发指南
```

## 开发流程

### 1. 创建功能分支

```bash
# 创建并切换到新分支
git checkout -b feature/新功能名称

# 或修复分支
git checkout -b fix/修复描述
```

### 2. 编写代码

#### 代码风格
- 遵循 PEP 8
- 使用中文注释
- 添加类型提示
- 编写文档字符串

#### 示例代码

```python
"""
模块功能说明
"""

import logging
from typing import Optional, List
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)


class ExampleClass:
    """示例类"""
    
    def __init__(self, name: str):
        """
        初始化方法
        
        Args:
            name: 名称
        """
        self.name = name
        logger.info(f"创建实例: {name}")
    
    def example_method(self, param: str) -> Optional[str]:
        """
        示例方法
        
        Args:
            param: 参数说明
        
        Returns:
            返回值说明
        
        Raises:
            ValueError: 参数错误
        """
        if not param:
            raise ValueError("参数不能为空")
        
        try:
            result = f"{self.name}_{param}"
            logger.debug(f"处理结果: {result}")
            return result
        except Exception as e:
            logger.error(f"处理失败: {e}")
            return None
```

### 3. 编写测试

#### 测试文件命名
- 测试文件：`test_模块名.py`
- 测试类：`Test类名`
- 测试方法：`test_功能描述`

#### 测试示例

```python
#!/usr/bin/env python3
"""
模块测试用例
"""

import sys
import pytest
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.example import ExampleClass


class TestExampleClass:
    """示例类测试"""
    
    def test_creation(self):
        """测试创建实例"""
        obj = ExampleClass("test")
        assert obj.name == "test"
    
    def test_example_method(self):
        """测试示例方法"""
        obj = ExampleClass("test")
        result = obj.example_method("param")
        assert result == "test_param"
    
    def test_example_method_empty_param(self):
        """测试空参数"""
        obj = ExampleClass("test")
        with pytest.raises(ValueError):
            obj.example_method("")
    
    @pytest.mark.asyncio
    async def test_async_method(self):
        """测试异步方法"""
        result = await some_async_function()
        assert result is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

### 4. 运行测试

```bash
# 运行所有测试
pytest -q

# 运行特定测试文件
pytest tests/test_example.py -v

# 运行特定测试方法
pytest tests/test_example.py::TestExampleClass::test_creation -v

# 运行带覆盖率的测试
pytest --cov=downloadkit
```

### 5. 提交代码

```bash
# 添加更改
git add .

# 提交更改
git commit -m "feat: 添加新功能"

# 推送到远程
git push origin feature/新功能名称
```

## 添加新平台

### 1. 创建平台文件

在 `downloadkit/platforms/` 创建新文件，例如 `new_platform.py`：

```python
"""
新平台适配器
"""

import httpx
from .base import BasePlatform, SongInfo, PlaylistInfo


class NewPlatform(BasePlatform):
    """新平台"""
    
    def __init__(self):
        self.name = "new_platform"
        self.base_url = "https://api.newplatform.com"
    
    async def search(self, keyword: str, limit: int = 20) -> list[SongInfo]:
        """搜索歌曲"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={"keyword": keyword, "limit": limit}
            )
            data = response.json()
            
            songs = []
            for item in data.get("songs", []):
                songs.append(SongInfo(
                    title=item["title"],
                    artist=item["artist"],
                    platform=self.name,
                    song_id=item["id"],
                    url=item.get("url")
                ))
            return songs
    
    async def get_song_url(self, song: SongInfo) -> str | None:
        """获取歌曲下载链接"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/song/{song.song_id}"
            )
            data = response.json()
            return data.get("url")
    
    async def get_playlist(self, playlist_id: str) -> PlaylistInfo:
        """获取歌单信息"""
        # 实现歌单解析
        pass
    
    def extract_playlist_id(self, url: str) -> str:
        """从URL提取歌单ID"""
        # 实现ID提取
        pass
```

### 2. 注册平台

在 `downloadkit/platforms/__init__.py` 添加：

```python
from .new_platform import NewPlatform

# 添加到平台列表
PLATFORMS = [
    NeteasePlatform(),
    QQMusicPlatform(),
    NewPlatform(),  # 新增
]

# 添加到平台映射
PLATFORM_MAP = {
    'netease': NeteasePlatform(),
    'qqmusic': QQMusicPlatform(),
    'new_platform': NewPlatform(),  # 新增
}
```

### 3. 添加API路由

在 `server.py` 添加：

```python
@app.post("/api/new-platform/search")
async def search_new_platform(keyword: str):
    """新平台搜索"""
    from downloadkit.platforms import NewPlatform
    platform = NewPlatform()
    results = await platform.search(keyword)
    return {"results": [vars(song) for song in results]}
```

### 4. 编写测试

```python
#!/usr/bin/env python3
"""
新平台测试用例
"""

import pytest
from downloadkit.platforms.new_platform import NewPlatform


class TestNewPlatform:
    """新平台测试"""
    
    @pytest.mark.asyncio
    async def test_search(self):
        """测试搜索功能"""
        platform = NewPlatform()
        results = await platform.search("test")
        assert isinstance(results, list)
    
    def test_extract_playlist_id(self):
        """测试ID提取"""
        platform = NewPlatform()
        url = "https://newplatform.com/playlist/12345"
        playlist_id = platform.extract_playlist_id(url)
        assert playlist_id == "12345"
```

## 调试技巧

### 1. 启用调试日志

```python
from downloadkit.logger import setup_logger

# 设置日志级别为DEBUG
logger = setup_logger(level=logging.DEBUG)
```

### 2. 使用断点调试

```python
# 在代码中添加断点
import pdb; pdb.set_trace()

# 或使用IDE的调试器
```

### 3. 查看网络请求

```python
import httpx

# 启用请求日志
async with httpx.AsyncClient(
    event_hooks={
        'request': [lambda req: print(f"Request: {req.method} {req.url}")],
        'response': [lambda resp: print(f"Response: {resp.status_code}")]
    }
) as client:
    response = await client.get("https://api.example.com")
```

## 常见问题

### Q: 如何解决依赖冲突？

```bash
# 查看依赖树
pip show downloadkit

# 升级依赖
pip install --upgrade package_name

# 清理缓存
pip cache purge
```

### Q: 如何解决编码问题？

```bash
# Windows设置环境变量
set PYTHONIOENCODING=utf-8

# 或在代码中指定编码
with open(file, 'r', encoding='utf-8') as f:
    content = f.read()
```

### Q: 如何解决FFmpeg问题？

```bash
# Windows (使用scoop)
scoop install ffmpeg

# 或下载预编译版本
# https://ffmpeg.org/download.html
```

## 发布流程

### 1. 更新版本号

在 `pyproject.toml` 更新版本号：

```toml
[project]
name = "downloadkit"
version = "0.4.0"  # 新版本号
```

### 2. 更新CHANGELOG.md

添加新版本的更新内容。

### 3. 运行测试

```bash
pytest -q
```

### 4. 构建包

```bash
pip install build
python -m build
```

### 5. 上传到PyPI

```bash
pip install twine
twine upload dist/*
```

## 贡献指南

### 提交规范

```
feat: 添加新功能
fix: 修复问题
docs: 更新文档
test: 添加测试
refactor: 重构代码
style: 代码格式调整
perf: 性能优化
chore: 构建/工具更改
```

### Pull Request流程

1. Fork项目
2. 创建功能分支
3. 编写代码和测试
4. 确保测试通过
5. 提交Pull Request
6. 等待代码审查
7. 合并到主分支
