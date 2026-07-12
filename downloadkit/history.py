"""
下载历史记录模块
使用SQLite存储下载记录，支持自动清理
"""

import sqlite3
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class HistoryRecord:
    """历史记录"""
    id: int
    url: str
    platform: str
    title: str
    author: str
    cover: str
    file_path: str
    file_size: int
    downloaded_at: str


class DownloadHistory:
    """下载历史管理"""
    
    def __init__(self, db_path: str = None, max_records: int = 1000):
        """
        初始化
        
        Args:
            db_path: 数据库文件路径
            max_records: 最大记录数，超过后自动清理旧记录
        """
        if db_path is None:
            db_path = str(Path.home() / ".downloadkit" / "history.db")
        
        self.db_path = db_path
        self.max_records = max_records
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    cover TEXT,
                    file_path TEXT,
                    file_size INTEGER,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建索引
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_downloaded_at 
                ON history(downloaded_at DESC)
            ''')
    
    def add_record(self, url: str, platform: str, title: str, author: str, 
                   cover: str, file_path: str, file_size: int):
        """
        添加下载记录
        
        Args:
            url: 原始URL
            platform: 平台名称
            title: 视频标题
            author: 作者
            cover: 封面URL
            file_path: 文件路径
            file_size: 文件大小
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO history (url, platform, title, author, cover, file_path, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (url, platform, title, author, cover, file_path, file_size))
            
            # 自动清理旧记录
            self._cleanup_old_records(conn)
    
    def _cleanup_old_records(self, conn):
        """清理旧记录，保留最新的max_records条"""
        cursor = conn.execute('SELECT COUNT(*) FROM history')
        count = cursor.fetchone()[0]
        
        if count > self.max_records:
            delete_count = count - self.max_records
            conn.execute('''
                DELETE FROM history 
                WHERE id IN (
                    SELECT id FROM history 
                    ORDER BY downloaded_at ASC 
                    LIMIT ?
                )
            ''', (delete_count,))
    
    def update_max_records(self, n: int):
        """动态更新最大记录数，更新后立即清理超标记录"""
        self.max_records = n
        with sqlite3.connect(self.db_path) as conn:
            self._cleanup_old_records(conn)

    def get_records(self, limit: int = 50, offset: int = 0) -> List[HistoryRecord]:
        """
        获取下载记录
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
        
        Returns:
            历史记录列表
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM history 
                ORDER BY downloaded_at DESC 
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            
            return [HistoryRecord(**dict(row)) for row in cursor.fetchall()]
    
    def search_records(self, keyword: str) -> List[HistoryRecord]:
        """
        搜索下载记录
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            匹配的历史记录列表
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM history 
                WHERE title LIKE ? OR author LIKE ?
                ORDER BY downloaded_at DESC
                LIMIT 50
            ''', (f'%{keyword}%', f'%{keyword}%'))
            
            return [HistoryRecord(**dict(row)) for row in cursor.fetchall()]
    
    def delete_record(self, record_id: int):
        """
        删除记录
        
        Args:
            record_id: 记录ID
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM history WHERE id = ?', (record_id,))
    
    def clear_history(self):
        """清空历史"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM history')
    
    def get_total_count(self) -> int:
        """获取总记录数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM history')
            return cursor.fetchone()[0]


# 全局实例
download_history = DownloadHistory(max_records=1000)
