"""
补完下载第1个作品的剩余实况照片
"""

import asyncio
import sys
sys.path.insert(0, '.')

from downloadkit.douyin import fetch_content, download_content, ContentType
from downloadkit.utils import get_download_dir
from pathlib import Path


async def main():
    aweme_id = "7632281762559982053"
    url = f"https://www.douyin.com/note/{aweme_id}"
    
    print(f"[下载] 开始解析: {url}")
    content = await fetch_content(url)
    
    if not content or not content.images:
        print("[错误] 未获取到内容")
        return
    
    print(f"[信息] 共 {len(content.images)} 张图片")
    
    # 检查已下载的文件
    download_dir = get_download_dir() / "animated"
    existing_files = list(download_dir.glob(f"douyin_{aweme_id}_motion_*.jpg"))
    existing_indices = set()
    
    for f in existing_files:
        # 提取序号
        name = f.stem
        parts = name.split("_motion_")
        if len(parts) > 1:
            try:
                idx = int(parts[1])
                existing_indices.add(idx)
            except ValueError:
                pass
    
    print(f"[信息] 已下载 {len(existing_indices)} 个: {sorted(existing_indices)}")
    
    # 计算需要下载的序号
    total = len(content.images)
    all_indices = set(range(1, total + 1))
    missing_indices = all_indices - existing_indices
    
    print(f"[信息] 需要下载 {len(missing_indices)} 个")
    
    if not missing_indices:
        print("[完成] 所有文件已下载")
        return
    
    # 逐个下载缺失的
    from downloadkit.douyin import DouyinParser
    import httpx
    
    parser = DouyinParser()
    
    async with httpx.AsyncClient() as client:
        for idx in sorted(missing_indices):
            print(f"\n[{idx}/{total}] 下载中...")
            
            # 获取对应的图片和视频
            img_idx = idx - 1
            if img_idx >= len(content.images):
                print(f"  跳过: 索引超出范围")
                continue
            
            image = content.images[img_idx]
            
            # 下载图片
            img_path = download_dir / f"douyin_{aweme_id}_photo_{idx}.jpg"
            if not img_path.exists():
                try:
                    await parser._download_file(client, image.url, img_path)
                    print(f"  图片下载完成: {img_path.name}")
                except Exception as e:
                    print(f"  图片下载失败: {e}")
                    continue
            
            # 检查是否有对应的视频（实况照片）
            video_url = getattr(image, 'video_url', None)
            if video_url:
                video_path = download_dir / f"douyin_{aweme_id}_video_{idx}.mp4"
                if not video_path.exists():
                    try:
                        await parser._download_file(client, video_url, video_path)
                        print(f"  视频下载完成: {video_path.name}")
                    except Exception as e:
                        print(f"  视频下载失败: {e}")
                        continue
                
                # 合并为Motion Photo
                motion_path = download_dir / f"douyin_{aweme_id}_motion_{idx}.jpg"
                if not motion_path.exists():
                    try:
                        from downloadkit.motion_photo import create_motion_photo
                        create_motion_photo(img_path, video_path, motion_path)
                        print(f"  合并完成: {motion_path.name}")
                        
                        # 删除临时文件
                        img_path.unlink(missing_ok=True)
                        video_path.unlink(missing_ok=True)
                    except Exception as e:
                        print(f"  合并失败: {e}")
            else:
                # 没有视频，直接重命名为motion格式
                motion_path = download_dir / f"douyin_{aweme_id}_motion_{idx}.jpg"
                if not motion_path.exists():
                    img_path.rename(motion_path)
                    print(f"  保存为: {motion_path.name}")
    
    print("\n[完成] 下载完成")


if __name__ == "__main__":
    asyncio.run(main())
