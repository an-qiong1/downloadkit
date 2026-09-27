"""P3-3 设置导出 / 导入

两条红线：

1. **导出只含四段** general / proxy / cookie / subscription ——
   cookie 段存的是文件路径不是 Cookie 内容，导出文件不携带登录态；
   subscription 是轮询偏好，换机迁移也该跟着走；多带一段就是
   把没必要的东西撒到磁盘上。
2. **导入段级白名单** —— 只认那四段且必须是对象，其余键全部丢弃。
   脏数据进 config.toml 没有地方报错，只会安静地留着，日后排查
   全靠猜。

另外钉住：导入前 confirm（覆盖是破坏性操作）、写完刷新 loadSettings、
FileReader 显式 utf-8、file input 用完清空（同一文件才选得动第二次）。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "js" / "settings.js").read_text(encoding="utf-8")


# ---------------- 界面 ----------------


def test_export_import_buttons_in_footer():
    """导出/导入与保存/恢复默认同排（都是一次性文件操作，别散落在别处）"""
    after = HTML.split('id="settings-save"')[1][:700]
    assert 'id="settings-reset"' in after
    assert 'id="settings-export"' in after, "缺导出按钮"
    assert 'id="settings-import"' in after, "缺导入按钮"
    assert 'id="settings-import-file"' in HTML, "缺隐藏的文件选择器"
    m = re.search(r'<input type="file" id="settings-import-file"[^>]*>', HTML)
    assert m and ".json" in m.group(0), "文件选择器该限 .json"
    assert "display:none" in m.group(0), "文件选择器该隐藏（由导入按钮代点）"


# ---------------- 导出 ----------------


def test_export_pulls_fresh_and_lands_four_sections():
    """导出现拉配置、只落四段、下载文件名带日期、释放 blob URL"""
    assert "function exportSettings" in JS
    assert "/api/settings/get" in JS.split("function exportSettings")[1][:600], \
        "导出该现拉配置，别拿页面里可能过期的值"
    body = JS.split("function exportSettings")[1].split("function handleImportFile")[0]
    for seg in ("general:", "proxy:", "cookie:", "subscription:"):
        assert seg in body, f"导出少了 {seg} 段"
    assert "JSON.stringify(payload, null, 2)" in body, "导出该是可读的缩进 JSON"
    assert "Blob" in body and "createObjectURL" in body
    assert "revokeObjectURL" in body, "blob URL 没释放，每次导出漏一块内存"
    assert "downloadkit-settings-" in body, "文件名没带标识"
    assert "toast('设置已导出" in body


# ---------------- 导入 ----------------


def test_import_validates_json_and_whitelists_sections():
    body = JS.split("function handleImportFile")[1].split("// ========== 事件绑定")[0]
    # JSON 解析失败要有中文提示，不能让 SyntaxError 冒到控制台
    assert "JSON.parse" in body and "不是有效的 JSON 文件" in body
    # 段级白名单是硬要求
    assert "['general', 'proxy', 'cookie', 'subscription']" in body, "没做段级白名单"
    assert "Array.isArray" in body, "没挡数组冒充设置对象"
    # 一段都没有 = 拒绝
    assert "没有可识别的设置段" in body
    # 覆盖前必须确认（P4-4 起原生 confirm 换成 uiConfirm 弹窗）
    assert "uiConfirm(" in body, "导入是覆盖性操作，缺确认"
    # 写完刷新界面
    assert "loadSettings()" in body, "导入后没刷新设置页"
    # 编码显式 + 同一文件可重复选
    assert "readAsText(file, 'utf-8')" in body, "FileReader 没指定 utf-8"
    assert "e.target.value = ''" in body, "file input 没清值，同一文件选不中第二次"
    # 带壳/裸两种结构都认
    assert "data.settings" in body, "没兼容 {settings:{...}} 带壳结构"


def test_import_wiring():
    assert "$('#settings-import-file').click()" in JS, "导入按钮没代点文件选择器"
    assert "addEventListener('change', handleImportFile)" in JS, "文件选择没绑 change"
    assert "addEventListener('click', exportSettings)" in JS, "导出按钮没绑定"
