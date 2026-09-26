"""fetch_creator 的链接作用域测试

这条 bug 很隐蔽且代价高：裸 'a[href*="/video/"]' 会把创作者主页
页脚的全站推荐（别人的视频）也抓进来，导致
  · 下载了别人的视频，任务标题却写着订阅的博主
  · 页脚每次加载都变，「新作品」判定反复漂移
所以必须有测试锁死「只取作品网格内的链接」。
"""

import pytest

from downloadkit.douyin_browser import (
    ANY_VIDEO_LINK_SELECTOR,
    POST_LINK_SELECTOR,
    DouyinBrowser,
)

GRID_HREFS = [
    "/video/7689023840848006451",
    "/video/7687872651049569586",
    "/video/7686739099671088424",
]
# 页脚推荐位：绝对 URL，还带 Baiduspider 参数
FOOTER_HREFS = [
    "https://www.douyin.com/video/7689498359911943475?source=Baiduspider",
    "https://www.douyin.com/video/7157002680504782087?source=Baiduspider-sdc",
]


class FakePage:
    """记录 fetch_creator 用了哪个选择器，并按选择器返回对应结果"""

    def __init__(self, grid=None, footer=None):
        self.grid = list(GRID_HREFS if grid is None else grid)
        self.footer = list(FOOTER_HREFS if footer is None else footer)
        self.selectors: list[str] = []
        self.closed = False

    async def goto(self, *a, **k):
        pass

    async def wait_for_timeout(self, *a, **k):
        pass

    async def close(self):
        self.closed = True

    async def evaluate(self, expr, *a, **k):
        # _extract_creator_meta 走的是 evaluate
        if "nickname" in str(expr):
            return {"nickname": "测试博主", "avatar": ""}
        return None

    async def eval_on_selector_all(self, selector, expr):
        self.selectors.append(selector)

        if "els.length" in str(expr):
            # 整页诊断：作品网格 + 页脚
            return len(self.grid) + len(self.footer)

        # 只有作用域选择器才应该被用来取作品链接
        if selector == 'a[href*="/video/"]':
            raise AssertionError(
                "fetch_creator 用了裸选择器，会把页脚推荐位的别人的视频抓进来"
            )

        if "user-post-list" in selector or "scroll-list" in selector:
            # 作用域选择器：只返回作品网格里的
            return list(self.grid)

        raise AssertionError(f"未预期的选择器: {selector}")


def _make_browser(page) -> DouyinBrowser:
    b = DouyinBrowser()

    async def fake_start():
        return None

    async def fake_get_page(reuse=True):
        return page

    b.start = fake_start
    b._get_page = fake_get_page
    return b


@pytest.mark.asyncio
async def test_fetch_creator_scopes_to_post_grid():
    """只能取作品网格里的链接，页脚推荐必须被排除"""
    page = FakePage()
    b = _make_browser(page)

    info = await b.fetch_creator("MS4wLjABAAAA_test", max_scrolls=2)

    ids = set(info.video_ids)
    # 网格里的三条都在
    for href in GRID_HREFS:
        assert href.rsplit("/", 1)[-1] in ids
    # 页脚那两条一条都不能进来
    for href in FOOTER_HREFS:
        aid = href.rsplit("/", 1)[-1].split("?")[0]
        assert aid not in ids, f"页脚推荐视频混进来了: {aid}"
    assert len(info.video_ids) == len(GRID_HREFS)


@pytest.mark.asyncio
async def test_fetch_creator_returns_ids_sorted_desc():
    info = await _make_browser(FakePage()).fetch_creator("MS4wLjABAAAA_test")
    assert info.video_ids == sorted(info.video_ids, reverse=True)


@pytest.mark.asyncio
async def test_fetch_creator_raises_on_empty_grid():
    """作品区一条都没抓到必须报错，不能返回空列表。

    空列表会被调用方拿去建基线 —— 空基线等于没有水位线，
    下一轮会把所有存量作品当成新作品下载下来。
    """
    page = FakePage(grid=[], footer=FOOTER_HREFS)
    b = _make_browser(page)

    with pytest.raises(RuntimeError) as e:
        await b.fetch_creator("MS4wLjABAAAA_test")

    assert "没抓到任何作品" in str(e.value)
    # 报错信息带上整页数量，方便判断是「选择器失效」还是「页面没渲染」
    assert str(len(FOOTER_HREFS)) in str(e.value)


@pytest.mark.asyncio
async def test_fetch_creator_closes_page_even_on_error():
    page = FakePage(grid=[])
    b = _make_browser(page)
    with pytest.raises(RuntimeError):
        await b.fetch_creator("MS4wLjABAAAA_test")
    assert page.closed, "出错时页面没关掉，会泄漏并占住 profile"


def test_selector_excludes_footer_by_construction():
    """选择器本身必须锚定 user-post-list / scroll-list"""
    assert "user-post-list" in POST_LINK_SELECTOR
    assert "scroll-list" in POST_LINK_SELECTOR
    # 不能是裸选择器
    assert POST_LINK_SELECTOR.strip() != 'a[href*="/video/"]'
    assert ANY_VIDEO_LINK_SELECTOR == 'a[href*="/video/"]'
