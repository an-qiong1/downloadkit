"""
代理配置模块
支持系统代理检测和手动配置
"""

import os
import sys
from typing import Optional


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
    """
    根据平台决定是否使用代理
    
    Args:
        platform: 平台名称 ('youtube', 'bilibili', 'douyin', 'xiaohongshu')
        config: 配置字典（可选）
    
    Returns:
        代理URL或None
    """
    # 从配置文件读取代理设置
    if config:
        proxy_config = config.get('proxy', {})
        
        # 检查是否启用代理
        if not proxy_config.get('enabled', True):
            return None
        
        # 检查平台特定代理
        platform_proxy = proxy_config.get(platform)
        if platform_proxy:
            return platform_proxy
        
        # 检查全局代理
        global_proxy = proxy_config.get('global')
        if global_proxy:
            return global_proxy
    
    # 默认策略
    # YouTube需要代理（国内无法直接访问）
    if platform == 'youtube':
        return get_system_proxy()
    
    # 其他平台不使用代理（Clash Verge规则模式会自动处理）
    # B站、抖音、小红书等国内平台直连
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
