"""快速检测抖音作品类型（不下载）"""

import asyncio
import sys
sys.path.insert(0, '.')

from downloadkit.douyin import fetch_content, ContentType


async def check_type(aweme_id: str) -> str:
    """检测单个作品类型"""
    try:
        content = await fetch_content(f"https://www.douyin.com/note/{aweme_id}")
        if content.content_type == ContentType.VIDEO:
            return "视频"
        elif content.content_type == ContentType.IMAGE:
            if content.images and any(hasattr(img, 'video_url') and img.video_url for img in content.images):
                return "实况照片"
            return "图文"
        else:
            return f"其他({content.content_type})"
    except Exception as e:
        return f"错误: {str(e)[:50]}"


async def main():
    # 从之前获取的作品ID列表
    aweme_ids = [
        "7644733746927076337", "7634427362952264121", "7611362878217636473",
        "7632281762559982053", "7552379142260395291", "7092363297680346376",
        "7609323362809552741", "7624516866979534586", "7440138874656951611",
        "7634802027911305649", "7354283055961410816", "7621111463797013241",
        "7632587775103175674", "7640833083252119675", "7447092757509770505",
        "7628957934454451633", "7631889625581261413", "7627103632887115889",
        "7622248652544115834", "7617089751309717413", "6975412820078791973",
        "7622589183970168569", "7613403539171393530", "7629318756988441073",
        "7640095479459531633", "7615923498841840634"
    ]
    
    print(f"开始检测 {len(aweme_ids)} 个作品类型...\n")
    
    results = {}
    motion_photos = []
    
    for i, aweme_id in enumerate(aweme_ids, 1):
        print(f"[{i}/{len(aweme_ids)}] {aweme_id}...", end=" ", flush=True)
        content_type = await check_type(aweme_id)
        print(content_type)
        
        results[aweme_id] = content_type
        if "实况" in content_type:
            motion_photos.append(aweme_id)
        
        await asyncio.sleep(1)
    
    print(f"\n{'='*50}")
    print(f"检测完成!")
    print(f"{'='*50}")
    
    type_count = {}
    for t in results.values():
        type_count[t] = type_count.get(t, 0) + 1
    
    print(f"\n类型统计:")
    for t, count in type_count.items():
        print(f"  {t}: {count}个")
    
    if motion_photos:
        print(f"\n实况照片 ({len(motion_photos)}个):")
        for pid in motion_photos:
            print(f"  https://www.douyin.com/note/{pid}")
    else:
        print(f"\n未发现实况照片")


if __name__ == "__main__":
    asyncio.run(main())
