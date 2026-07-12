"""
浏览器Cookie获取模块
支持从Edge、Chrome、Firefox浏览器获取Cookie
"""

import sys
from typing import Optional, Dict


def get_browser_cookie(domain: str, browser: str = 'edge') -> Dict[str, str]:
    """
    从浏览器获取指定域名的Cookie
    
    Args:
        domain: 域名 (如 '.bilibili.com')
        browser: 浏览器类型 ('edge', 'chrome', 'firefox')
    
    Returns:
        Cookie字典 {name: value}
    """
    try:
        import browser_cookie3
    except ImportError:
        raise RuntimeError(
            "browser_cookie3未安装，请运行: pip install browser_cookie3"
        )
    
    # 根据浏览器类型获取Cookie
    if browser == 'edge':
        cj = browser_cookie3.edge(domain_name=domain)
    elif browser == 'chrome':
        cj = browser_cookie3.chrome(domain_name=domain)
    elif browser == 'firefox':
        cj = browser_cookie3.firefox(domain_name=domain)
    else:
        raise ValueError(f"不支持的浏览器: {browser}")
    
    # 转换为字典
    cookies = {}
    for cookie in cj:
        cookies[cookie.name] = cookie.value
    
    return cookies


def get_cookie_string(domain: str, browser: str = 'edge') -> str:
    """
    获取Cookie字符串格式
    
    Args:
        domain: 域名
        browser: 浏览器类型
    
    Returns:
        Cookie字符串 (key1=value1; key2=value2; ...)
    """
    cookies = get_browser_cookie(domain, browser)
    return '; '.join([f"{k}={v}" for k, v in cookies.items()])


def get_bilibili_cookie(browser: str = 'edge') -> Dict[str, str]:
    """
    获取B站Cookie
    
    Args:
        browser: 浏览器类型
    
    Returns:
        Cookie字典
    """
    return get_browser_cookie('.bilibili.com', browser)


def get_bilibili_cookie_string(browser: str = 'edge') -> str:
    """
    获取B站Cookie字符串
    
    Args:
        browser: 浏览器类型
    
    Returns:
        Cookie字符串
    """
    return get_cookie_string('.bilibili.com', browser)


def get_douyin_cookie(browser: str = 'edge') -> Dict[str, str]:
    """
    获取抖音Cookie

    Args:
        browser: 浏览器类型 ('edge', 'chrome', 'firefox')

    Returns:
        Cookie字典
    """
    return get_browser_cookie('.douyin.com', browser)


def get_douyin_cookie_string(browser: str = 'edge') -> str:
    """
    获取抖音Cookie字符串

    Args:
        browser: 浏览器类型

    Returns:
        Cookie字符串
    """
    cookies = get_douyin_cookie(browser)
    # 抖音需要的关键 cookie：ttwid 和 sessionid
    return '; '.join([f"{k}={v}" for k, v in cookies.items()])


def get_youtube_cookie(browser: str = 'edge') -> Dict[str, str]:
    """
    获取YouTube Cookie
    
    Args:
        browser: 浏览器类型
    
    Returns:
        Cookie字典
    """
    return get_browser_cookie('.youtube.com', browser)


def get_youtube_cookie_string(browser: str = 'edge') -> str:
    """
    获取YouTube Cookie字符串
    
    Args:
        browser: 浏览器类型
    
    Returns:
        Cookie字符串
    """
    return get_cookie_string('.youtube.com', browser)


def save_cookie_to_file(domain: str, browser: str = 'edge', filepath: str = None):
    """
    将Cookie保存到文件（Netscape格式，供yt-dlp使用）
    
    Args:
        domain: 域名
        browser: 浏览器类型
        filepath: 保存路径
    """
    cookies = get_browser_cookie(domain, browser)
    
    if filepath is None:
        filepath = f"cookies_{domain.replace('.', '_')}.txt"
    
    with open(filepath, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n\n")
        
        for name, value in cookies.items():
            # 格式: domain  flag  path  secure  expiration  name  value
            f.write(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")
    
    return filepath


# 测试函数
if __name__ == "__main__":
    print("测试浏览器Cookie获取...")
    
    # 测试B站Cookie
    try:
        cookies = get_bilibili_cookie('edge')
        print(f"获取到 {len(cookies)} 个B站Cookie")
        
        # 检查关键Cookie
        if 'SESSDATA' in cookies:
            print("✓ SESSDATA Cookie存在")
        else:
            print("✗ SESSDATA Cookie不存在")
        
        if 'bili_jct' in cookies:
            print("✓ bili_jct Cookie存在")
        else:
            print("✗ bili_jct Cookie不存在")
    
    except Exception as e:
        print(f"获取B站Cookie失败: {e}")
    
    # 测试YouTube Cookie
    try:
        cookies = get_youtube_cookie('edge')
        print(f"获取到 {len(cookies)} 个YouTube Cookie")
    
    except Exception as e:
        print(f"获取YouTube Cookie失败: {e}")
