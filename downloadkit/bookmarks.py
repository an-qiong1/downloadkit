# -*- coding: utf-8 -*-
"""浏览器书签 HTML 解析（Netscape Bookmark File Format）。

导出路径：Chrome/Edge → 书签管理器 → 右上角 ⋮ → 导出书签；
Firefox → 显示全部书签 → 导入和备份 → 导出书签到 HTML。

文件结构（嵌套 <DL>/<DT>/<H3>，闭合标签大量省略，正则易错，
故用标准库 html.parser 状态机）：

    <!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
    <DT><H3 ADD_DATE="1727000000">追剧</H3>
        <DL><p>
        <DT><A HREF="https://..." ADD_DATE="1727000001">某剧-第1集</A>
        <DT><H3>子文件夹</H3>
            <DL><p>
            <DT><A HREF="...">...</A>
            </DL><p>
        </DL><p>
    </DL><p>

状态机要点（均按真实导出文件踩过的坑）：
  · <DT> 无闭合标签、<DL> 内混排游离 <p> → 忽略
  · </H3> 后先暂存文件夹，等下一个 <DL> 出现才入栈
  · <A> 缺 </A> 时靠下一个 <DT>/<DL>/<H3>/<A> 触发兜底 flush
  · 顶层直接 <DT><A>（无 H3）→ 挂根节点
  · 无名 <DL>（找不到对应 H3，如文件最外层）→ 匿名容器，序列化时并回父层
  · 非书签 HTML（无 NETSCAPE doctype 且无 H3+DL 结构）→ ValueError，
    避免把普通网页的 <a> 全部当成书签导入
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterator


@dataclass
class Bookmark:
    """一条书签链接"""
    title: str
    url: str
    add_date: int = 0


@dataclass
class Folder:
    """书签文件夹（name 为空表示匿名容器，序列化时展开到父层）"""
    name: str = ""
    add_date: int = 0
    children: list[Any] = field(default_factory=list)


def _to_int(v: Any) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


class _BookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Folder()
        self._stack: list[Folder] = [self.root]
        self._buf: list[str] = []
        self._in_h3 = False
        self._in_a = False
        self._href = ""
        self._add_date = 0
        self._pending: Folder | None = None   # </H3> 已解析、等 <DL> 入栈
        self.link_count = 0

    # ---------- 内部 ----------
    def _flush_a(self) -> None:
        """收尾一条链接（正常 </A> 或被下一个结构标签打断时都走这里）"""
        if not self._in_a:
            return
        title = "".join(self._buf).strip()
        href = (self._href or "").strip()
        self._in_a = False
        self._buf = []
        if href.lower().startswith(("http://", "https://")) and title:
            self._stack[-1].children.append(
                Bookmark(title=title, url=href, add_date=self._add_date)
            )
            self.link_count += 1

    def _flush_pending(self) -> None:
        """H3 后没等到 <DL>（空文件夹/结构残缺）→ 直接挂当前层"""
        if self._pending is not None:
            self._stack[-1].children.append(self._pending)
            self._pending = None

    # ---------- HTMLParser 回调 ----------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "a":
            self._flush_a()
            self._flush_pending()
            self._in_a = True
            self._buf = []
            self._href = attrs_d.get("href") or ""
            self._add_date = _to_int(attrs_d.get("add_date"))
        elif tag == "h3":
            self._flush_a()
            self._flush_pending()
            self._in_h3 = True
            self._buf = []
            self._add_date = _to_int(attrs_d.get("add_date"))
        elif tag == "dl":
            self._flush_a()
            if self._pending is not None:
                folder, self._pending = self._pending, None
            else:
                folder = Folder()          # 匿名容器（文件最外层/无 H3 的 DL）
            self._stack[-1].children.append(folder)
            self._stack.append(folder)
        elif tag == "dt":
            # DT 后应接 H3 或 A；上一个 H3 若没等到 DL，在这里收掉
            self._flush_a()
            self._flush_pending()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._flush_a()
        elif tag == "h3":
            if self._in_h3:
                name = "".join(self._buf).strip()
                self._in_h3 = False
                self._buf = []
                self._pending = Folder(name=name, add_date=self._add_date)
        elif tag == "dl":
            if len(self._stack) > 1:
                self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_h3 or self._in_a:
            self._buf.append(data)

    def close(self) -> None:
        self._flush_a()
        self._flush_pending()
        super().close()


# ---------- 序列化 ----------

def _looks_like_bookmarks(text: str) -> bool:
    head = text[:4096].lower()
    if "netscape-bookmark-file" in head:
        return True
    # 个别工具导出时丢了 doctype：有 DL+H3+A 结构也算
    low = text[:65536].lower()
    return "<dl" in low and "<h3" in low and "<a href" in low


def _node_to_dict(node: Any) -> dict[str, Any] | None:
    if isinstance(node, Bookmark):
        return {
            "type": "link",
            "title": node.title,
            "url": node.url,
            "add_date": node.add_date,
        }
    if isinstance(node, Folder):
        if not node.name:
            return None                      # 匿名容器：由调用方展开
        return {
            "type": "folder",
            "name": node.name,
            "add_date": node.add_date,
            "children": _children_to_list(node.children),
        }
    return None


def _children_to_list(children: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in children:
        if isinstance(ch, Folder) and not ch.name:
            out.extend(_children_to_list(ch.children))   # 匿名容器展开并回父层
            continue
        d = _node_to_dict(ch)
        if d is not None:
            out.append(d)
    return out


def _count(tree: list[dict[str, Any]], kind: str) -> int:
    n = 0
    for node in tree:
        if node.get("type") == kind:
            n += 1
        if node.get("type") == "folder":
            n += _count(node.get("children") or [], kind)
    return n


def parse_bookmarks_html(text: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """解析书签 HTML → (树, 统计)。

    Returns:
        (tree, {"links": 链接数, "folders": 文件夹数})
        树节点: {"type": "folder", "name", "add_date", "children": [...]}
                {"type": "link", "title", "url", "add_date"}

    Raises:
        ValueError: 不是书签格式的 HTML
    """
    if not text or not text.strip():
        raise ValueError("文件为空")
    if not _looks_like_bookmarks(text):
        raise ValueError("不是浏览器导出的书签 HTML 文件（缺少 NETSCAPE-Bookmark 结构）")

    parser = _BookmarkParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # noqa: BLE001 — 残缺 HTML 尽量保留已解析部分
        pass

    tree = _children_to_list(parser.root.children)
    return tree, {"links": _count(tree, "link"), "folders": _count(tree, "folder")}


def flatten_bookmarks(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """树展平为 [{"url", "title", "folder"}...]，URL 去重保序（首见标题为准）。

    folder 为层级路径（"追剧/国漫"），顶层链接为 ""。
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(nodes: list[dict[str, Any]], path: str) -> None:
        for n in nodes:
            if n.get("type") == "folder":
                sub = f"{path}/{n.get('name') or ''}".strip("/") if path else (n.get("name") or "")
                walk(n.get("children") or [], sub)
            elif n.get("type") == "link":
                url = (n.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append({
                    "url": url,
                    "title": (n.get("title") or "").strip(),
                    "folder": path,
                })

    walk(tree, "")
    return out


def iter_folders(tree: list[dict[str, Any]]) -> Iterator[list[str]]:
    """迭代所有文件夹路径（供选择器/统计用）"""
    def walk(nodes: list[dict[str, Any]], path: list[str]) -> Iterator[list[str]]:
        for n in nodes:
            if n.get("type") == "folder":
                cur = path + [n.get("name") or ""]
                yield cur
                yield from walk(n.get("children") or [], cur)

    yield from walk(tree, [])
