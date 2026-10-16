"""服务端 POST /api/bookmarks/import 端点单元测试

覆盖：
  - 正常导入 → 返回 tree / links / folders
  - 空白、非书签 HTML、0 条 http 链接 → 400
  - BOM 前缀剥离、丢 doctype 的工具导出
  - 嵌套文件夹计数、重复 URL 不去重
  - 非 http 协议（mailto / javascript / ftp）不计数
  - 无标题链接不计数、add_date 保留

测试策略：直接 import route 函数调用，不启动真实服务，纯本地无网络。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import api_bookmarks_import, BookmarkImportRequest


# ============================ 样本 HTML ============================

NORMAL_HTML = (
    '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
    '<DL><p>\n'
    '  <DT><A HREF="https://a.com/v/1" ADD_DATE="1727000001">第一个视频</A>\n'
    '  <DT><H3>追剧 [2024]</H3>\n'
    '  <DL><p>\n'
    '    <DT><A HREF="https://a.com/v/2">第 [1] 集</A>\n'
    '    <DT><A HREF="https://a.com/v/1">重复链接</A>\n'
    '  </DL><p>\n'
    '</DL><p>\n'
)


def _req(html: str) -> BookmarkImportRequest:
    return BookmarkImportRequest(html=html)


# ============================ 正常路径 ============================

class TestImportNormal:
    @pytest.mark.asyncio
    async def test_normal_returns_tree_links_folders(self):
        r = await api_bookmarks_import(_req(NORMAL_HTML))
        assert r["links"] == 3        # 顶层 1 + 文件夹内 2（重复不去重）
        assert r["folders"] == 1      # "追剧 [2024]"
        assert isinstance(r["tree"], list)
        assert len(r["tree"]) == 2    # 顶层 = 1 链接 + 1 文件夹

    @pytest.mark.asyncio
    async def test_tree_node_types_and_fields(self):
        r = await api_bookmarks_import(_req(NORMAL_HTML))
        top_link = next(n for n in r["tree"] if n["type"] == "link")
        assert top_link["title"] == "第一个视频"
        assert top_link["url"] == "https://a.com/v/1"

        folder = next(n for n in r["tree"] if n["type"] == "folder")
        assert folder["name"] == "追剧 [2024]"
        assert isinstance(folder["children"], list)
        assert len(folder["children"]) == 2

    @pytest.mark.asyncio
    async def test_duplicate_urls_both_counted(self):
        """links 计数不去重（去重由 CLI 的 --urls / flatten 负责）。"""
        r = await api_bookmarks_import(_req(NORMAL_HTML))
        urls = [
            n["url"] for n in r["tree"]
            if n["type"] == "link"
        ]
        assert len(urls) == 1         # 顶层只有 1 条
        folder = next(n for n in r["tree"] if n["type"] == "folder")
        inner = [c["url"] for c in folder["children"] if c["type"] == "link"]
        assert inner.count("https://a.com/v/1") == 1

    @pytest.mark.asyncio
    async def test_add_date_preserved(self):
        r = await api_bookmarks_import(_req(NORMAL_HTML))
        top_link = next(n for n in r["tree"] if n["type"] == "link")
        assert top_link["add_date"] == 1727000001


# ============================ 400 路径 ============================

class TestImportBadRequest:
    @pytest.mark.asyncio
    async def test_empty_string_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            await api_bookmarks_import(_req(""))
        assert exc.value.status_code == 400
        assert "文件为空" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_whitespace_only_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            await api_bookmarks_import(_req("   \n\t  "))
        assert exc.value.status_code == 400
        assert "文件为空" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_non_bookmark_html_raises_400(self):
        """普通网页 HTML（无 NETSCAPE 结构）→ 不是书签文件。"""
        html = "<html><body><h1>hello</h1><p>nothing</p></body></html>"
        with pytest.raises(HTTPException) as exc:
            await api_bookmarks_import(_req(html))
        assert exc.value.status_code == 400
        assert "书签" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_bookmark_html_without_http_links_raises_400(self):
        """结构合法但 0 条 http 链接（只有 mailto）→ 明确提示。"""
        html = (
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            '<DL><p>\n'
            '  <DT><H3>联系人</H3>\n'
            '  <DL><p>\n'
            '    <DT><A HREF="mailto:test@test.com">邮件</A>\n'
            '  </DL><p>\n'
            '</DL><p>\n'
        )
        with pytest.raises(HTTPException) as exc:
            await api_bookmarks_import(_req(html))
        assert exc.value.status_code == 400
        assert "未解析到任何书签链接" in str(exc.value.detail)


# ============================ 边界 ============================

class TestImportEdgeCases:
    @pytest.mark.asyncio
    async def test_bom_prefix_stripped(self):
        """BOM 前缀被剥掉后仍正常解析。"""
        r = await api_bookmarks_import(_req("\ufeff" + NORMAL_HTML))
        assert r["links"] == 3

    @pytest.mark.asyncio
    async def test_missing_doctype_still_parsed(self):
        """个别工具导出时丢了 DOCTYPE：有 DL+H3+A 结构也算书签。"""
        html = (
            '<DL><p>\n'
            '  <DT><H3>我的收藏</H3>\n'
            '  <DL><p>\n'
            '    <DT><A HREF="https://b.com/x/1">某视频</A>\n'
            '  </DL><p>\n'
            '</DL><p>\n'
        )
        r = await api_bookmarks_import(_req(html))
        assert r["links"] == 1
        assert r["folders"] == 1

    @pytest.mark.asyncio
    async def test_non_http_schemes_not_counted(self):
        """javascript: / ftp: 等非 http 链接不计数。"""
        html = (
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            '<DL><p>\n'
            '  <DT><A HREF="javascript:void(0)">JS</A>\n'
            '  <DT><A HREF="ftp://f.com/file">FTP</A>\n'
            '  <DT><A HREF="https://ok.com/real">真实</A>\n'
            '</DL><p>\n'
        )
        r = await api_bookmarks_import(_req(html))
        assert r["links"] == 1

    @pytest.mark.asyncio
    async def test_empty_title_not_counted(self):
        """空标题的 <a> 不计数（解析器要求 href + title 都非空）。"""
        html = (
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            '<DL><p>\n'
            '  <DT><A HREF="https://c.com/empty"></A>\n'
            '  <DT><A HREF="https://c.com/ok">有标题</A>\n'
            '</DL><p>\n'
        )
        r = await api_bookmarks_import(_req(html))
        assert r["links"] == 1

    @pytest.mark.asyncio
    async def test_truncated_html_preserves_partial(self):
        """残缺 HTML 尽量保留已解析部分（不抛 500）。"""
        html = (
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            '<DL><p>\n'
            '  <DT><A HREF="https://d.com/one">一</A>\n'
            '  <DT><A HREF="https://d.com/two">二'
        )
        r = await api_bookmarks_import(_req(html))
        assert r["links"] == 2        # close() 会 flush 未闭合的最后一条 <a>
