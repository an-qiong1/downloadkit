"""
代理配置模块
支持系统代理检测和手动配置
"""

import os
import sys
from typing import Optional

# 代理三态（P3-1）：关闭 / 跟随系统 / 手动
MODES = ("off", "system", "manual")
DEFAULT_MODE = "system"


def resolve_mode(proxy_config: Optional[dict]) -> str:
    """把 proxy 配置解析成三态之一，含旧配置兼容。

    旧配置只有 enabled 布尔开关，按「尽量不改用户现有行为」推导：

      · enabled=false               → off
      · enabled=true 且填过任一地址 → manual（尊重用户手填的地址，
        忽略它等于代理悄悄失效）
      · enabled=true 且全空         → system（老版本 youtube 下载的实际
        行为就是「走系统代理」，推 system 保证升级前后一致）

    Args:
        proxy_config: config["proxy"] 节，可能为 None / 缺失

    Returns:
        "off" | "system" | "manual"
    """
    pc = proxy_config or {}
    mode = str(pc.get("mode") or "").strip()
    if mode in MODES:
        return mode

    if pc.get("enabled", True) is False:
        return "off"
    for key in ("global", "youtube", "bilibili", "douyin", "xiaohongshu"):
        if str(pc.get(key) or "").strip():
            return "manual"
    return DEFAULT_MODE


def get_system_proxy() -> Optional[str]:
    """
    获取系统代理设置
    
    Returns:
        代理URL (如 http://127.0.0.1:7890) 或 None
    """
    # 1. 检查环境变量
    proxy = os.environ.get('HTTP_PROXY') or os.environ.get('HTTPS_PROXY') or os.environ.get('ALL_PROXY')
    if proxy:
        return proxy
    
    # 2. Windows系统代理
    if sys.platform == 'win32':
        return _get_windows_proxy()
    
    # 3. macOS系统代理
    elif sys.platform == 'darwin':
        return _get_macos_proxy()
    
    # 4. Linux系统代理
    elif sys.platform.startswith('linux'):
        return _get_linux_proxy()
    
    return None


def _get_windows_proxy() -> Optional[str]:
    """
    获取Windows系统代理
    
    Returns:
        代理URL或None
    """
    try:
        import winreg
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        
        # 检查代理是否启用
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        
        if proxy_enable:
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            winreg.CloseKey(key)
            
            if proxy_server:
                # 处理格式
                if not proxy_server.startswith('http'):
                    proxy_server = f"http://{proxy_server}"
                return proxy_server
        
        winreg.CloseKey(key)
    
    except Exception:
        pass
    
    return None


def _get_macos_proxy() -> Optional[str]:
    """
    获取macOS系统代理
    
    Returns:
        代理URL或None
    """
    try:
        import subprocess
        
        # 尝试获取HTTP代理
        result = subprocess.run(
            ['networksetup', '-getwebproxy', 'Wi-Fi'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if 'Enabled: Yes' in line:
                    # 获取代理服务器
                    result2 = subprocess.run(
                        ['networksetup', '-getwebproxy', 'Wi-Fi'],
                        capture_output=True,
                        text=True
                    )
                    for line2 in result2.stdout.strip().split('\n'):
                        if 'Server:' in line2:
                            server = line2.split(':')[1].strip()
                            port = '80'  # 默认端口
                            if 'Port:' in result2.stdout:
                                for line3 in result2.stdout.strip().split('\n'):
                                    if 'Port:' in line3:
                                        port = line3.split(':')[1].strip()
                            return f"http://{server}:{port}"
    
    except Exception:
        pass
    
    return None


def _get_linux_proxy() -> Optional[str]:
    """
    获取Linux系统代理
    
    Returns:
        代理URL或None
    """
    # 检查常见的代理环境变量
    for var in ['http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
        proxy = os.environ.get(var)
        if proxy:
            return proxy
    
    return None


def get_proxy_for_platform(platform: str, config: dict = None) -> Optional[str]:
    """按平台解析最终生效的代理（P3-1 三态）。

    三态（config["proxy"]["mode"]）：
      · off    关闭 —— 一律直连，手动填的地址全部忽略
      · system 跟随系统 —— 用系统代理设置，手动地址忽略
      · manual 手动 —— 平台专属地址 > 全局地址 > 直连

    旧配置兼容（只有 enabled 开关、没有 mode）由 resolve_mode 推导：
      · enabled=false                    → off
      · enabled=true 且填过任一地址      → manual（尊重手动值）
      · enabled=true 且全空              → system（老版本 youtube 的
        实际行为就是「走系统代理」，推 system 保证升级不改行为）

    Args:
        platform: 平台名称 ('youtube', 'bilibili', 'douyin', 'xiaohongshu')
        config: 整份配置字典（可选）；不传 = 按空配置解析（默认 system）

    Returns:
        代理URL或None（None = 直连）
    """
    pc = (config or {}).get("proxy") or {}

    mode = resolve_mode(pc)
    if mode == "off":
        return None

    if mode == "system":
        return get_system_proxy()

    # manual：平台专属优先，其次全局，都没填就直连
    for key in (platform, "global"):
        value = str(pc.get(key) or "").strip()
        if value:
            return value
    return None


def get_proxy_dict(platform: str, config: dict = None) -> Optional[dict]:
    """
    获取代理字典格式（用于httpx）
    
    Args:
        platform: 平台名称
        config: 配置字典
    
    Returns:
        代理字典或None
    """
    proxy = get_proxy_for_platform(platform, config)
    
    if proxy:
        return {
            "http://": proxy,
            "https://": proxy,
        }
    
    return None


def get_yt_dlp_proxy(platform: str = 'youtube', config: dict = None) -> Optional[str]:
    """
    获取yt-dlp格式的代理
    
    Args:
        platform: 平台名称
        config: 配置字典
    
    Returns:
        代理URL或None
    """
    return get_proxy_for_platform(platform, config)


# 测试函数
if __name__ == "__main__":
    print("测试代理配置...")
    
    # 测试系统代理
    proxy = get_system_proxy()
    if proxy:
        print(f"系统代理: {proxy}")
    else:
        print("未检测到系统代理")
    
    # 测试各平台代理
    for platform in ['youtube', 'bilibili', 'douyin', 'xiaohongshu']:
        proxy = get_proxy_for_platform(platform)
        if proxy:
            print(f"{platform}代理: {proxy}")
        else:
            print(f"{platform}代理: 直连")
