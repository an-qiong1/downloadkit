# -*- coding: utf-8 -*-
"""downloadkit.bookmarks 单测：Netscape 书签 HTML 各种真实导出变体。"""
import pytest

from downloadkit.bookmarks import (
    flatten_bookmarks,
    iter_folders,
    parse_bookmarks_html,
)

CHROMIUM_EXPORT = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1727000000">书签栏</H3>
    <DL><p>
        <DT><A HREF="https://www.example.com/a" ADD_DATE="1727000001">链接A</A>
        <DT><H3 ADD_DATE="1727000002">追剧</H3>
        <DL><p>
            <DT><A HREF="https://www.example.com/ep1" ADD_DATE="1727000003">某剧 第1集</A>
            <DT><A HREF="https://www.example.com/ep2" ADD_DATE="1727000004">某剧 第2集</A>
            <DT><H3>国漫</H3>
            <DL><p>
                <DT><A HREF="https://www.example.com/dm1">斗罗大陆 第01集</A>
            </DL><p>
        </DL><p>
    </DL><p>
</DL><p>
"""


def test_chromium_nested_tree():
    tree, stats = parse_bookmarks_html(CHROMIUM_EXPORT)
    assert stats["links"] == 4
    assert stats["folders"] == 3          # 书签栏 / 追剧 / 国漫

    root = tree[0]
    assert root["type"] == "folder"
    assert root["name"] == "书签栏"
    assert root["add_date"] == 1727000000
    assert root["children"][0]["url"] == "https://www.example.com/a"

    drama = root["children"][1]
    assert drama["type"] == "folder" and drama["name"] == "追剧"
    assert drama["children"][0]["title"] == "某剧 第1集"
    guoman = drama["children"][2]
    assert guoman["name"] == "国漫"
    assert guoman["children"][0]["title"] == "斗罗大陆 第01集"


def test_flatten_with_folder_path_and_dedupe():
    tree, _ = parse_bookmarks_html(CHROMIUM_EXPORT)
    items = flatten_bookmarks(tree)
    assert [i["url"] for i in items] == [
        "https://www.example.com/a",
        "https://www.example.com/ep1",
        "https://www.example.com/ep2",
        "https://www.example.com/dm1",
    ]
    assert items[0]["folder"] == "书签栏"
    assert items[1]["folder"] == "书签栏/追剧"
    assert items[3]["folder"] == "书签栏/追剧/国漫"

    # 重复 URL 去重（同一链接收藏在多个文件夹）
    dup = tree + [dict(tree[0])]  # 不影响去重逻辑的构造
    flat = flatten_bookmarks(dup)
    urls = [i["url"] for i in flat]
    assert len(urls) == len(set(urls))


def test_top_level_links_without_h3():
    """文件最外层直接 <DT><A>（无 H3 包裹）"""
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><A HREF="https://x.com/1">顶层一</A>
<DT><A HREF="https://x.com/2">顶层二</A>
</DL><p>
"""
    tree, stats = parse_bookmarks_html(html)
    assert stats == {"links": 2, "folders": 0}
    assert [n["title"] for n in tree] == ["顶层一", "顶层二"]
    assert flatten_bookmarks(tree)[0]["folder"] == ""


def test_empty_folder_and_missing_close_tags():
    """空文件夹（H3 后无 DL）与缺 </A> 的容错"""
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><H3>空文件夹</H3>
<DT><A HREF="https://x.com/loose">缺闭合A
<DT><H3>有内容</H3>
<DL><p>
<DT><A HREF="https://x.com/in">在里面</A>
</DL><p>
</DL><p>
"""
    tree, stats = parse_bookmarks_html(html)
    assert stats["links"] == 2
    names = [n["name"] for n in tree if n["type"] == "folder"]
    assert names == ["空文件夹", "有内容"]


def test_entities_and_special_chars():
    """&amp; 等实体解码，HREF 属性带引号/单引号"""
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><A HREF='https://x.com/s?a=1&amp;b=2'>A &amp; B 标题</A>
<DT><A HREF="https://x.com/t">标题 &lt;测试&gt; &quot;引号&quot;</A>
</DL><p>
"""
    tree, stats = parse_bookmarks_html(html)
    assert stats["links"] == 2
    assert tree[0]["url"] == "https://x.com/s?a=1&b=2"
    assert tree[0]["title"] == "A & B 标题"
    assert tree[1]["title"] == '标题 <测试> "引号"'


def test_non_http_href_skipped():
    """javascript:/mailto: 等非 http 链接不导入"""
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><A HREF="javascript:void(0)">脚本链接</A>
<DT><A HREF="mailto:a@b.com">邮件</A>
<DT><A HREF="https://ok.com/">正常</A>
</DL><p>
"""
    tree, stats = parse_bookmarks_html(html)
    assert stats["links"] == 1
    assert tree[0]["title"] == "正常"


def test_reject_non_bookmark_html():
    """普通网页不能被当成书签导入"""
    html = "<html><body><h1>文章</h1><a href='https://a.com'>link</a></body></html>"
    with pytest.raises(ValueError):
        parse_bookmarks_html(html)
    with pytest.raises(ValueError):
        parse_bookmarks_html("")


def test_iter_folders_paths():
    tree, _ = parse_bookmarks_html(CHROMIUM_EXPORT)
    paths = ["/".join(p) for p in iter_folders(tree)]
    assert paths == ["书签栏", "书签栏/追剧", "书签栏/追剧/国漫"]
