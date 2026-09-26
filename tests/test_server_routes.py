"""server.py 路由注册顺序回归测试

FastAPI / Starlette 按**注册顺序**匹配路径。带路径参数的路由
（`/api/subscriptions/{sec_uid}`）如果注册在静态子路由
（`/api/subscriptions/poller`）之前，静态路由会被参数先吃掉，
表现为接口返回 404 且错误文案是「没有订阅这个创作者」。

这个坑 2026-09-26 踩过一次：A5 的轮询接口加在文件末尾，
本地单元测试全绿（测的是 poller 模块本身），但真实请求 404。
所以专门留一条测试锁住顺序。
"""

import pytest

URL = "/api/subscriptions/poller"


def _first_match(method: str, url: str):
    """按 Starlette 的方式找第一个能匹配上这个 URL 的路由"""
    from server import app

    for route in app.routes:
        if getattr(route, "methods", None) and method not in route.methods:
            continue
        regex = getattr(route, "path_regex", None)
        if regex is None:
            continue
        if regex.match(url):
            return route
    return None


def test_get_poller_route_not_shadowed():
    route = _first_match("GET", URL)
    assert route is not None, "GET /api/subscriptions/poller 根本没注册"
    assert route.path == URL, (
        f"/poller 被 {route.path} 先匹配掉了：静态子路由必须注册在"
        f"参数化路由 /api/subscriptions/{{sec_uid}} 之前"
    )


def test_post_poller_route_not_shadowed():
    route = _first_match("POST", URL)
    assert route is not None, "POST /api/subscriptions/poller 根本没注册"
    assert route.path == URL, (
        f"/poller POST 被 {route.path} 先匹配掉了"
    )


def test_param_route_still_works_for_real_sec_uid():
    """修顺序别修过头：正常的创作者详情路由必须还能匹配"""
    sec = "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"
    route = _first_match("GET", f"/api/subscriptions/{sec}")
    assert route is not None
    assert route.path == "/api/subscriptions/{sec_uid}"


def test_check_all_route_not_shadowed():
    """/check-all 和 /{sec}/check 分段数不同，不该互相吃"""
    route = _first_match("POST", "/api/subscriptions/check-all")
    assert route is not None
    assert route.path == "/api/subscriptions/check-all"
