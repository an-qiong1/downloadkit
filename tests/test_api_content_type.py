# -*- coding: utf-8 -*-
"""api() 请求必须带 Content-Type: application/json

2026-09-27 实测踩到（用户报：设置页「选择目录」「打开」都报
「请求失败: Input should be a valid dictionary or object...」）：

    api() 只在 body 是**对象**时才自动 JSON.stringify + 设
    Content-Type。settings.js 有 6 处自己先 stringify 成字符串，
    于是 fetch 对 string body 兜底发 text/plain —— 老版 FastAPI
    不看 header 直接 json.loads，一直没炸；9-26 .venv 升到
    fastapi 0.141.1 后，见非 application/json 就不解析 body，
    Pydantic 收到裸字符串，422。

    炸的只有走 string body 的 6 处（选择目录 / 打开 / 读浏览器
    Cookie ×2 / 存 Cookie ×2），传对象的 26 处全部正常，所以
    症状零散、难从代码一眼看出来。

    前端发法决定服务端行为，纯服务端测试拦不住这个坑，所以用
    静态测试钉死两端：
      1. 所有 js 里 body: 后面不许出现 JSON.stringify（统一交
         api() 处理，杜绝 string body）；
      2. api() 保留 string body 的 Content-Type 兜底（将来有人
         再传字符串也不至于掉回 text/plain）。
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "downloadkit", "static", "js")

# body: JSON.stringify(...) —— 自己 stringify 的老写法
_INLINE_STRINGIFY = re.compile(r"body\s*:\s*JSON\.stringify")
# api(path, { ... body: <expr> ... }) 里 body: 后面的取值（截到逗号/换行/右括号）
_BODY_VALUE = re.compile(r"body\s*:\s*([^,}\n]+)")


def _js_files():
    return [
        os.path.join(JS_DIR, f)
        for f in sorted(os.listdir(JS_DIR))
        if f.endswith(".js")
    ]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_no_inline_stringify_bodies():
    """body 只许传对象 —— 由 api() 统一 stringify + 设 header"""
    offenders = []
    for path in _js_files():
        for i, line in enumerate(_read(path).splitlines(), 1):
            if _INLINE_STRINGIFY.search(line):
                offenders.append(f"{os.path.basename(path)}:{i}")
    assert not offenders, (
        "这些位置把 body 手动 stringify 成了字符串："
        + ", ".join(offenders)
        + " —— api() 只给对象 body 设 Content-Type: application/json，"
        "string body 会被 fetch 发成 text/plain，FastAPI 0.141+ 直接 422。"
        "改成 body: { ... } 传对象。"
    )


def test_api_has_json_fallback_for_string_body():
    """api() 必须保留 string body 的 Content-Type 兜底"""
    src = _read(os.path.join(JS_DIR, "utils.js"))
    assert "typeof opts.body === 'string'" in src, (
        "api() 丢了 string body 的处理分支 —— 万一将来又有人传字符串，"
        "fetch 会把 body 发成 text/plain，服务端 422 "
        "「Input should be a valid dictionary」。"
    )
    # 兜底分支里要真的设上 application/json
    m = re.search(
        r"typeof opts\.body === 'string'[^}]*Content-Type[^}]*application/json",
        src,
        re.S,
    )
    assert m, "string body 分支里没有设置 Content-Type: application/json"


def test_all_bodies_are_objects_or_api_stringified():
    """body: 取值只许是对象字面量/变量 —— JSON.stringify 已被第一条禁止"""
    bad = []
    for path in _js_files():
        src = _read(path)
        # 只看 api( 调用块里的 body:（模板字符串里的 fetch body 不在此列，
        # 全项目只有 utils.js 一处 fetch）
        for m in _BODY_VALUE.finditer(src):
            val = m.group(1).strip()
            if val.startswith("JSON.stringify"):
                bad.append(f"{os.path.basename(path)}: {val[:60]}")
    assert not bad, "body 传了字符串：" + "; ".join(bad)
