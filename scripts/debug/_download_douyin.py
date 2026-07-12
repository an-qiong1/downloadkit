"""临时脚本：调用 downloadkit.douyin 解析并下载抖音视频"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from downloadkit.douyin import fetch_content, download_content

async def main():
    share_text = "8.99 复制打开抖音，看看【半岛铁盒的作品】 https://v.douyin.com/Z7oxG24Abio/ 06/10 A@t.rE cnD:/ :5pm"
    print("=== 解析抖音链接...")
    content = await fetch_content(share_text)
    print(f"标题: {content.title}")
    print(f"作者: {content.author}")
    print(f"类型: {content.content_type}")
    print(f"ID: {content.item_id}")
    if content.video_url_no_watermark:
        print(f"无水印视频地址: {content.video_url_no_watermark}")
    if content.images:
        print(f"图片数量: {len(content.images)}")
    print("\n=== 开始下载 ===")
    output_dir = Path(__file__).parent / "downloads"
    output_dir.mkdir(exist_ok=True)
    paths = await download_content(content, str(output_dir))
    print(f"\n下载完成，文件:")
    for p in paths:
        size_mb = p.stat().st_size / 1048576
        print(f"  {p.name}  ({size_mb:.2f} MB)")

if __name__ == "__main__":
    asyncio.run(main())
