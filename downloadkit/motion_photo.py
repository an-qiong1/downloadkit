"""
Google Motion Photo 格式生成模块
将 JPEG + MP4 合并为单个 Motion Photo 文件

支持多种XMP格式：
1. GCamera:MotionPhoto - 谷歌/小米/三星相册识别
2. OpCamera 命名空间 - OPPO/一加相册识别

参考微信处理实况照片的方式，实现跨品牌互通

参考规范：
- https://developer.android.com/media/platform/motion-photo-format
- https://github.com/doodspav/motionphoto
"""

import struct
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

from .utils import CREATE_NO_WINDOW

logger = logging.getLogger(__name__)


# XMP 模板 - 参考微信处理方式，兼容所有设备
# 兼容：谷歌相册、小米相册、三星相册、OPPO相册、一加相册等
XMP_TEMPLATE = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.1.0-jc003">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
        xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"
        xmlns:OpCamera="http://ns.oplus.com/photos/1.0/camera/"
        xmlns:Container="http://ns.google.com/photos/1.0/container/"
        xmlns:Item="http://ns.google.com/photos/1.0/container/item/"
      GCamera:MotionPhoto="1"
      GCamera:MotionPhotoVersion="1"
      GCamera:MotionPhotoPresentationTimestampUs="{timestamp}"
      OpCamera:MotionPhotoPrimaryPresentationTimestampUs="{timestamp}"
      OpCamera:MotionPhotoVideoStart="0"
      OpCamera:MotionPhotoVideoEnd="0"
      OpCamera:MotionPhotoOwner="oplus"
      OpCamera:OLivePhotoVersion="2"
      OpCamera:VideoLength="{video_offset}">
      <Container:Directory>
        <rdf:Seq>
          <rdf:li rdf:parseType="Resource">
            <Container:Item
              Item:Mime="image/jpeg"
              Item:Semantic="Primary"
              Item:Length="0"
              Item:Padding="0"/>
          </rdf:li>
          <rdf:li rdf:parseType="Resource">
            <Container:Item
              Item:Mime="video/mp4"
              Item:Semantic="MotionPhoto"
              Item:Length="{video_offset}"
              Item:Padding="0"/>
          </rdf:li>
        </rdf:Seq>
      </Container:Directory>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>"""


def _read_jpeg_dimensions(jpeg_data: bytes) -> tuple[int, int]:
    """
    从 JPEG 数据中读取图片尺寸（从 SOF0 段）
    
    Returns:
        (width, height) 元组
    """
    # 查找 SOF0 标记 (0xFFC0)
    sof0_marker = b'\xff\xc0'
    pos = jpeg_data.find(sof0_marker)
    
    if pos == -1:
        # 尝试 SOF2 (渐进式 JPEG)
        sof0_marker = b'\xff\xc2'
        pos = jpeg_data.find(sof0_marker)
    
    if pos == -1:
        raise ValueError("无法在 JPEG 中找到 SOF 段")
    
    # SOF0 结构：
    # 2 bytes: 标记 (FFC0)
    # 2 bytes: 段长度
    # 1 bytes: 精度 (通常为 8)
    # 2 bytes: 图片高度 (big-endian)
    # 2 bytes: 图片宽度 (big-endian)
    height = struct.unpack('>H', jpeg_data[pos + 5:pos + 7])[0]
    width = struct.unpack('>H', jpeg_data[pos + 7:pos + 9])[0]
    
    return width, height


def _create_exif_segment(width: int, height: int) -> bytes:
    """
    创建标准的 Exif APP1 段
    
    使用 LONG 类型存储宽高（与参考文件一致）
    设置 Orientation=0（参考文件值）
    添加 UserComment 字段（OPPO标识）
    """
    # Exif 头
    exif_header = b'Exif\x00\x00'
    
    # TIFF 头 (MM = Big Endian)
    tiff_header = b'MM\x00*\x00\x00\x00\x08'
    
    # IFD0 条目数量
    ifd0_count = struct.pack('>H', 4)  # 4 个条目
    
    # IFD0 条目 (每个条目 12 字节)
    # 条目1: ImageWidth (使用 LONG 类型 = 0x0004)
    entry1 = struct.pack('>HHI', 0x0100, 0x0004, 1)  # Tag, Type=LONG, Count=1
    entry1 += struct.pack('>I', width)
    
    # 条目2: ImageHeight (使用 LONG 类型 = 0x0004)
    entry2 = struct.pack('>HHI', 0x0101, 0x0004, 1)  # Tag, Type=LONG, Count=1
    entry2 += struct.pack('>I', height)
    
    # 条目3: Orientation (使用 LONG 类型 = 0x0004，值为 0)
    entry3 = struct.pack('>HHI', 0x0112, 0x0004, 1)  # Tag, Type=LONG, Count=1
    entry3 += struct.pack('>I', 0)  # Orientation = 0
    
    # 条目4: ExifIFD 指针
    exif_ifd_offset = 8 + 2 + 4 * 12 + 4  # TIFF头 + 条目数 + 4个条目 + 下一个IFD偏移
    entry4 = struct.pack('>HHI', 0x8769, 0x0004, 1)  # Tag, Type=LONG, Count=1
    entry4 += struct.pack('>I', exif_ifd_offset)
    
    # 下一个 IFD 偏移 (0 表示没有下一个 IFD)
    next_ifd = struct.pack('>I', 0)
    
    # 组装 IFD0 数据
    ifd0_data = ifd0_count + entry1 + entry2 + entry3 + entry4 + next_ifd
    
    # Exif IFD 条目数量
    exif_ifd_count = struct.pack('>H', 2)  # 2 个条目
    
    # Exif IFD 条目
    # 条目1: LightSource (0x9208)
    exif_entry1 = struct.pack('>HHI', 0x9208, 0x0003, 1)  # Tag, Type=SHORT, Count=1
    exif_entry1 += struct.pack('>I', 0)  # LightSource = 0
    
    # 条目2: UserComment (0x9286)
    user_comment = b'oplus_10485792'
    # UserComment 需要特殊格式：前8字节是字符集标识，后面是实际内容
    # 使用 ASCII 字符集
    user_comment_data = b'ASCII\x00\x00\x00' + user_comment
    user_comment_offset = exif_ifd_offset + 2 + 2 * 12 + 4  # 计算偏移量
    
    exif_entry2 = struct.pack('>HHI', 0x9286, 0x0007, len(user_comment_data))  # Tag, Type=UNDEFINED, Count=len
    exif_entry2 += struct.pack('>I', user_comment_offset)
    
    # Exif IFD 下一个 IFD 偏移
    exif_next_ifd = struct.pack('>I', 0)
    
    # 组装 Exif IFD 数据
    exif_ifd_data = exif_ifd_count + exif_entry1 + exif_entry2 + exif_next_ifd
    
    # 组装完整的 Exif 数据
    exif_data = exif_header + tiff_header + ifd0_data + exif_ifd_data + user_comment_data
    
    # 计算 APP1 段长度
    segment_length = len(exif_data) + 2  # +2 for length field
    
    # 构建 APP1 段
    app1_segment = struct.pack('>HH', 0xFFE1, segment_length) + exif_data
    
    return app1_segment


def _transcode_to_hevc(mp4_path: Path) -> bytes:
    """
    使用 FFmpeg 将 H.264 视频转码为 HEVC (H.265)
    
    Args:
        mp4_path: 输入 MP4 文件路径
    
    Returns:
        转码后的 MP4 数据
    """
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        # 构建 FFmpeg 命令
        cmd = [
            'ffmpeg',
            '-i', str(mp4_path),
            '-c:v', 'libx265',      # 使用 HEVC 编码器
            '-tag:v', 'hvc1',        # 设置正确的 codec tag
            '-c:a', 'copy',          # 保持音频不变
            '-movflags', '+faststart',  # 将 moov 放在 mdat 之前
            '-y',                    # 覆盖输出文件
            str(tmp_path)
        ]
        
        logger.info("正在转码视频为 HEVC...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
            creationflags=CREATE_NO_WINDOW,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 转码失败: {result.stderr}")
        
        # 读取转码后的数据
        hevc_data = tmp_path.read_bytes()
        logger.info(f"HEVC 转码完成，大小: {len(hevc_data)} bytes")
        
        return hevc_data
    
    finally:
        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()


def _get_video_dimensions(mp4_path: Path) -> tuple[int, int]:
    """
    获取视频文件的宽度和高度
    
    Args:
        mp4_path: MP4 文件路径
    
    Returns:
        (width, height) 元组
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            str(mp4_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(',')
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.warning(f"获取视频尺寸失败: {e}")
    
    return None, None


def _resize_video_to_match(mp4_path: Path, target_width: int, target_height: int) -> bytes:
    """
    将视频缩放到指定尺寸，保持宽高比并填充黑边
    
    Args:
        mp4_path: 输入 MP4 文件路径
        target_width: 目标宽度
        target_height: 目标高度
    
    Returns:
        缩放后的 MP4 数据
    """
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        # 使用 FFmpeg 缩放视频，保持宽高比并填充黑边
        # scale: 缩放到目标尺寸内，保持宽高比
        # pad: 填充黑边到目标尺寸
        vf_filter = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black"
        
        cmd = [
            'ffmpeg',
            '-i', str(mp4_path),
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            '-y',
            str(tmp_path)
        ]
        
        logger.info(f"缩放视频到 {target_width}x{target_height}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                creationflags=CREATE_NO_WINDOW)
        
        if result.returncode != 0:
            raise RuntimeError(f"视频缩放失败: {result.stderr}")
        
        resized_data = tmp_path.read_bytes()
        logger.info(f"视频缩放完成，大小: {len(resized_data)} bytes")
        
        return resized_data
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def create_motion_photo(
    jpeg_path: Path | str,
    mp4_path: Path | str,
    output_path: Path | str,
    presentation_timestamp_us: int = 0,
    transcode_hevc: bool = False  # 默认使用H.264，兼容性最好
) -> Path:
    """
    将 JPEG + MP4 合并为 Google Motion Photo
    
    Args:
        jpeg_path: JPEG 图片路径
        mp4_path: MP4 视频路径
        output_path: 输出文件路径
        presentation_timestamp_us: 关键帧时间戳（微秒），默认 0 表示使用视频开头
        transcode_hevc: 是否将视频转码为 HEVC（默认 False，使用 H.264 编码以获得最佳兼容性）
    
    Returns:
        输出文件路径
    """
    jpeg_path = Path(jpeg_path)
    mp4_path = Path(mp4_path)
    output_path = Path(output_path)
    
    # 验证输入文件
    if not jpeg_path.exists():
        raise FileNotFoundError(f"JPEG 文件不存在: {jpeg_path}")
    if not mp4_path.exists():
        raise FileNotFoundError(f"MP4 文件不存在: {mp4_path}")
    
    # 读取文件数据
    jpeg_data = jpeg_path.read_bytes()
    
    # 如果不是 JPEG（PNG/WebP 等），自动转换
    if jpeg_data[:2] != b'\xff\xd8':
        logger.info("输入不是 JPEG，尝试自动转换...")
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(jpeg_data))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            jpeg_data = buf.getvalue()
            logger.info(f"转换为 JPEG 成功，大小: {len(jpeg_data)} bytes")
        except ImportError:
            raise ValueError(f"PIL 未安装，无法转换非 JPEG 文件: {jpeg_path}")
        except Exception as e:
            raise ValueError(f"无法转换为 JPEG: {jpeg_path}, 错误: {e}")
    
    # 验证 MP4 文件头 (ftyp box)
    mp4_data = mp4_path.read_bytes()
    if len(mp4_data) < 8 or mp4_data[4:8] != b'ftyp':
        raise ValueError(f"无效的 MP4 文件: {mp4_path}")
    
    # 读取 JPEG 真实尺寸
    try:
        img_width, img_height = _read_jpeg_dimensions(jpeg_data)
        logger.info(f"图片尺寸: {img_width}x{img_height}")
    except Exception as e:
        logger.warning(f"无法读取图片尺寸: {e}，使用默认值")
        img_width, img_height = 0, 0
    
    # 检查视频尺寸，如果宽高比不匹配则缩放视频
    vid_width, vid_height = _get_video_dimensions(mp4_path)
    if vid_width and vid_height and img_width and img_height:
        img_ratio = img_width / img_height
        vid_ratio = vid_width / vid_height
        
        logger.info(f"视频尺寸: {vid_width}x{vid_height}")
        
        # 如果宽高比差异超过阈值，缩放视频
        if abs(img_ratio - vid_ratio) > 0.1:
            logger.info(f"宽高比不匹配 (图片:{img_ratio:.2f} vs 视频:{vid_ratio:.2f})，缩放视频...")
            try:
                mp4_data = _resize_video_to_match(mp4_path, img_width, img_height)
                # 更新mp4_path为临时文件
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                    tmp.write(mp4_data)
                    mp4_path = Path(tmp.name)
            except Exception as e:
                logger.warning(f"视频缩放失败: {e}，使用原始视频")
                mp4_data = mp4_path.read_bytes()
        else:
            logger.info("宽高比匹配，无需缩放")
            mp4_data = mp4_path.read_bytes()
    else:
        # 转码视频为 HEVC（如果启用）
        if transcode_hevc:
            try:
                mp4_data = _transcode_to_hevc(mp4_path)
            except Exception as e:
                logger.warning(f"HEVC 转码失败: {e}，使用原始 H.264 视频")
                mp4_data = mp4_path.read_bytes()
        else:
            mp4_data = mp4_path.read_bytes()
    
    # MicroVideoOffset = MP4 视频大小
    video_size = len(mp4_data)
    
    # 构建 XMP 元数据
    xmp = XMP_TEMPLATE.format(
        timestamp=presentation_timestamp_us,
        video_offset=video_size
    )
    xmp_bytes = xmp.encode('utf-8')
    
    # 创建 Exif APP1 段（使用真实尺寸）
    exif_segment = _create_exif_segment(img_width, img_height)
    
    # 将 XMP 注入到 JPEG
    jpeg_with_xmp = _inject_xmp_to_jpeg(jpeg_data, xmp_bytes, exif_segment)
    
    # 写入输出文件：JPEG + XMP + MP4
    with open(output_path, 'wb') as f:
        f.write(jpeg_with_xmp)
        f.write(mp4_data)
    
        logger.info(f"创建成功: {output_path}")
        logger.info(f"  图片尺寸: {img_width}x{img_height}")
        logger.info(f"  图片大小: {len(jpeg_data)} bytes")
        logger.info(f"  视频大小: {video_size} bytes")
        logger.info(f"  视频编码: {'HEVC' if transcode_hevc else 'H.264'}")
        logger.info(f"  MicroVideoOffset: {video_size}")
        logger.info(f"  输出大小: {output_path.stat().st_size} bytes")
    
    return output_path


def _inject_xmp_to_jpeg(jpeg_data: bytes, xmp_bytes: bytes, exif_segment: bytes) -> bytes:
    """
    将 XMP 元数据注入到 JPEG 文件
    
    Args:
        jpeg_data: 原始 JPEG 数据
        xmp_bytes: XMP 数据
        exif_segment: Exif APP1 段
    """
    # 验证 JPEG 文件头
    if jpeg_data[:2] != b'\xff\xd8':
        raise ValueError("无效的 JPEG 文件")
    
    # XMP 命名空间
    xmp_namespace = b'http://ns.adobe.com/xap/1.0/\x00'
    
    # 构建 XMP APP1 段数据
    xmp_app1_data = xmp_namespace + xmp_bytes
    
    # 计算 XMP APP1 段长度
    xmp_segment_length = len(xmp_app1_data) + 2
    if xmp_segment_length > 65535:
        raise ValueError("XMP 数据过大，超过 APP1 段限制")
    
    # 构建 XMP APP1 段
    xmp_app1_segment = bytes([0xFF, 0xE1]) + struct.pack('>H', xmp_segment_length) + xmp_app1_data
    
    # 检查原始 JPEG 是否已经有 APP1 段
    # 如果有，需要删除或替换
    pos = 2  # 跳过 SOI
    while pos < len(jpeg_data) - 4:
        if jpeg_data[pos:pos+2] == b'\xff\xe1':
            # 找到 APP1 段，获取长度
            seg_len = struct.unpack('>H', jpeg_data[pos+2:pos+4])[0]
            # 删除原始 APP1 段
            jpeg_data = jpeg_data[:pos] + jpeg_data[pos+2+seg_len:]
            continue
        elif jpeg_data[pos:pos+2] == b'\xff\xda':
            # 找到 SOS 段，停止
            break
        elif jpeg_data[pos:pos+2] == b'\xff\xd9':
            # 找到 EOI 段，停止
            break
        elif jpeg_data[pos] == 0xff and jpeg_data[pos+1] in [0xe0, 0xe2, 0xdb, 0xc0, 0xc2, 0xc4]:
            # 其他标记段，跳过
            if pos+3 < len(jpeg_data):
                seg_len = struct.unpack('>H', jpeg_data[pos+2:pos+4])[0]
                pos += 2 + seg_len
            else:
                break
        else:
            pos += 1
    
    # 在 SOI 之后插入 Exif 和 XMP 段（分开的 APP1 段）
    result = jpeg_data[:2] + exif_segment + xmp_app1_segment + jpeg_data[2:]
    
    return result


def extract_video_from_motion_photo(motion_photo_path: Path | str, output_video_path: Path | str) -> Path:
    """
    从 Motion Photo 中提取视频
    
    Args:
        motion_photo_path: Motion Photo 文件路径
        output_video_path: 输出视频路径
    
    Returns:
        输出视频路径
    """
    motion_photo_path = Path(motion_photo_path)
    output_video_path = Path(output_video_path)
    
    data = motion_photo_path.read_bytes()
    
    # 查找 MP4 的起始位置（ftyp box）
    ftyp_pos = data.find(b'\x00\x00\x00\x18ftyp', 0)
    if ftyp_pos == -1:
        ftyp_pos = data.find(b'\x00\x00\x00\x1cftyp', 0)
    if ftyp_pos == -1:
        # 尝试其他 ftyp box 大小
        ftyp_pos = data.find(b'ftyp')
        if ftyp_pos == -1:
            raise ValueError("未找到嵌入的 MP4 视频")
        # 回退到 box 大小字段
        ftyp_pos = max(0, ftyp_pos - 4)
    
    # 提取视频数据
    video_data = data[ftyp_pos:]
    output_video_path.write_bytes(video_data)
    logger.info(f"提取视频成功: {output_video_path}")
    return output_video_path


def is_motion_photo(file_path_or_data: Path | str | bytes) -> bool:
    """
    检测文件是否是 Motion Photo
    
    通过查找 XMP 元数据中的 GCamera:MicroVideo 标记
    
    Args:
        file_path_or_data: 文件路径或文件数据（字节）
    """
    # 如果是字节数据，直接检查
    if isinstance(file_path_or_data, bytes):
        return b'GCamera:MicroVideo' in file_path_or_data[:8192]
    
    # 否则作为文件路径处理
    file_path = Path(file_path_or_data)
    
    if not file_path.exists():
        return False
    
    # 读取文件头部（XMP 通常在前几 KB）
    with open(file_path, 'rb') as f:
        header = f.read(8192)
    
    # 查找 MicroVideo 标记
    return b'GCamera:MicroVideo' in header


def get_motion_photo_info(file_path: Path | str) -> Optional[dict]:
    """
    获取 Motion Photo 的元数据信息
    
    Returns:
        包含元数据的字典，如果不是 Motion Photo 则返回 None
    """
    file_path = Path(file_path)
    
    if not is_motion_photo(file_path):
        return None
    
    data = file_path.read_bytes()
    
    info = {
        "is_motion_photo": True,
        "file_size": len(data),
    }
    
    # 查找视频起始位置
    ftyp_pos = data.find(b'ftyp')
    if ftyp_pos != -1:
        ftyp_pos = max(0, ftyp_pos - 4)
        info["video_offset"] = ftyp_pos
        info["video_size"] = len(data) - ftyp_pos
        info["image_size"] = ftyp_pos
    
    return info


# ============ Apple Live Photo 转换功能 ============

import uuid
import re
import tempfile
import os

def _extract_jpeg_from_motion_photo(data: bytes) -> bytes:
    """从 Motion Photo 数据中提取 JPEG"""
    # 查找 XMP 中的 MicroVideoOffset
    xmp_start = data.find(b'<x:xmpmeta')
    xmp_end = data.find(b'</x:xmpmeta>')
    
    if xmp_start != -1 and xmp_end != -1:
        xmp_text = data[xmp_start:xmp_end + 13].decode('utf-8', errors='ignore')
        offset_match = re.search(r'GCamera:MicroVideoOffset="(\d+)"', xmp_text)
        
        if offset_match:
            mp4_size = int(offset_match.group(1))
            jpeg_end = len(data) - mp4_size
            jpeg_data = data[:jpeg_end]
        else:
            # 从 ftyp 位置截断
            ftyp_pos = data.find(b'ftyp')
            if ftyp_pos != -1:
                jpeg_data = data[:ftyp_pos - 4]
            else:
                raise ValueError("无法确定 JPEG 结束位置")
    else:
        ftyp_pos = data.find(b'ftyp')
        if ftyp_pos != -1:
            jpeg_data = data[:ftyp_pos - 4]
        else:
            raise ValueError("无法确定 JPEG 结束位置")
    
    # 确保 JPEG 以 FFD9 结尾
    if jpeg_data[-2:] != b'\xff\xd9':
        eoi_pos = jpeg_data.rfind(b'\xff\xd9')
        if eoi_pos != -1:
            jpeg_data = jpeg_data[:eoi_pos + 2]
    
    return jpeg_data


def _extract_mp4_from_motion_photo(data: bytes) -> bytes:
    """从 Motion Photo 数据中提取 MP4"""
    ftyp_pos = data.find(b'ftyp')
    if ftyp_pos == -1:
        raise ValueError("未找到嵌入的 MP4 视频")
    
    # 回退到 box 大小字段
    mp4_start = max(0, ftyp_pos - 4)
    return data[mp4_start:]


def _convert_mp4_to_mov_with_metadata(mp4_data: bytes, content_identifier: str) -> bytes:
    """将 MP4 转换为 QuickTime MOV 并添加 Apple Live Photo 元数据"""
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_mp4:
        tmp_mp4.write(mp4_data)
        tmp_mp4_path = tmp_mp4.name
    
    tmp_mov_path = tmp_mp4_path.replace('.mp4', '.mov')
    
    try:
        # 使用 moviepy 转换
        try:
            from moviepy import VideoFileClip
        except ImportError:
            from moviepy.editor import VideoFileClip
        
        video = VideoFileClip(tmp_mp4_path)
        
        # 导出为 MOV 格式
        video.write_videofile(
            tmp_mov_path,
            codec='libx264',
            audio_codec='aac',
            preset='medium',
            fps=video.fps or 15,
            logger=None  # 静默输出
        )
        
        video.close()
        
        # 读取生成的 MOV 文件
        with open(tmp_mov_path, 'rb') as f:
            mov_data = f.read()
        
        # 添加 Apple Live Photo 元数据
        mov_data = _add_quicktime_metadata(mov_data, content_identifier)
        
        return mov_data
        
    finally:
        # 清理临时文件
        for path in [tmp_mp4_path, tmp_mov_path]:
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except:
                    pass


def _add_quicktime_metadata(mov_data: bytes, content_identifier: str) -> bytes:
    """添加 QuickTime 元数据到 MOV 文件"""
    
    # 创建 content.identifier 元数据
    content_id_metadata = _create_quicktime_metadata_atom(
        'com.apple.quicktime.content.identifier',
        content_identifier.encode('utf-8')
    )
    
    # 创建 still-image-time 元数据
    still_image_metadata = _create_quicktime_metadata_atom(
        'com.apple.quicktime.still-image-time',
        b'\xff'  # 0xFF 表示静态图像时间
    )
    
    # 找到 moov 原子并在其末尾添加元数据
    moov_pos = mov_data.find(b'moov')
    if moov_pos == -1:
        # 如果没有 moov，在 ftyp 后添加
        ftyp_end = mov_data.find(b'ftyp')
        if ftyp_end != -1:
            ftyp_size = struct.unpack('>I', mov_data[ftyp_end-4:ftyp_end])[0]
            insert_pos = ftyp_end - 4 + ftyp_size
        else:
            insert_pos = 0
    else:
        # moov 原子的结束位置
        moov_size = struct.unpack('>I', mov_data[moov_pos-4:moov_pos])[0]
        insert_pos = moov_pos - 4 + moov_size
    
    # 创建 udta 原子来包含这些元数据
    metadata_atoms = content_id_metadata + still_image_metadata
    udta_atom = _create_atom(b'udta', metadata_atoms)
    
    # 在 moov 后插入 udta
    mov_data = mov_data[:insert_pos] + udta_atom + mov_data[insert_pos:]
    
    return mov_data


def _create_quicktime_metadata_atom(key: str, value: bytes) -> bytes:
    """创建 QuickTime 元数据原子"""
    # 创建键原子
    key_atom = _create_atom(b'key ', struct.pack('>I', 0x01) + key.encode('utf-8'))
    
    # 创建值原子
    value_atom = _create_atom(b'data', struct.pack('>III', 0x01, 0, 0) + value)
    
    # 创建 ilst 条目
    ilst_entry = _create_atom(b'\xa9' + key[:3].encode('utf-8'), key_atom + value_atom)
    
    return ilst_entry


def _create_atom(atom_type: bytes, data: bytes) -> bytes:
    """创建一个 QuickTime/MP4 原子"""
    size = 8 + len(data)
    return struct.pack('>I', size) + atom_type + data


def create_apple_live_photo(
    jpeg_path: Path | str,
    mp4_path: Path | str,
    output_dir: Path | str,
    output_name: str = None
) -> tuple[Path, Path]:
    """
    将 JPEG + MP4 转换为 Apple Live Photo 格式
    
    Apple Live Photo 由两个文件组成：
    1. JPEG 文件（带 Apple Maker Notes）
    2. QuickTime MOV 文件（带 content.identifier 和 still-image-time 元数据）
    
    两者通过共同的 ContentIdentifier (UUID) 关联。
    
    Args:
        jpeg_path: JPEG 图片路径
        mp4_path: MP4 视频路径
        output_dir: 输出目录
        output_name: 输出文件名（不含扩展名），默认使用 jpeg_path 的文件名
    
    Returns:
        (jpeg_output_path, mov_output_path) 元组
    """
    jpeg_path = Path(jpeg_path)
    mp4_path = Path(mp4_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if output_name is None:
        output_name = jpeg_path.stem
    
    # 生成唯一的 ContentIdentifier
    content_identifier = str(uuid.uuid4()).upper()
    logger.info(f"生成 ContentIdentifier: {content_identifier}")
    
    # 读取输入文件
    jpeg_data = jpeg_path.read_bytes()
    mp4_data = mp4_path.read_bytes()
    
    # 转换 MP4 为 MOV 并添加元数据
    logger.info("转换 MP4 为 QuickTime MOV...")
    mov_data = _convert_mp4_to_mov_with_metadata(mp4_data, content_identifier)
    
    # 保存输出文件
    jpeg_output = output_dir / f"{output_name}.jpg"
    mov_output = output_dir / f"{output_name}.mov"
    
    jpeg_output.write_bytes(jpeg_data)
    mov_output.write_bytes(mov_data)
    
    logger.info("创建成功:")
    logger.info(f"  JPEG: {jpeg_output}")
    logger.info(f"  MOV:  {mov_output}")
    logger.info(f"  大小: JPEG={len(jpeg_data):,} bytes, MOV={len(mov_data):,} bytes")
    
    return jpeg_output, mov_output


def create_apple_live_photo_from_motion_photo(
    motion_photo_path: Path | str,
    output_dir: Path | str = None,
    keep_google_format: bool = True
) -> tuple[Path, Path]:
    """
    从 Google Motion Photo 转换为 Apple Live Photo 格式
    
    Args:
        motion_photo_path: Motion Photo 文件路径
        output_dir: 输出目录，默认为源文件所在目录的 live_photo_output 子目录
        keep_google_format: 是否保留原始 Google Motion Photo 文件
    
    Returns:
        (jpeg_output_path, mov_output_path) 元组
    """
    motion_photo_path = Path(motion_photo_path)
    
    if output_dir is None:
        output_dir = motion_photo_path.parent / 'apple_live_photo'
    output_dir = Path(output_dir)
    logger.info(f"转换: {motion_photo_path.name}")
    
    # 读取 Motion Photo 数据
    data = motion_photo_path.read_bytes()
    
    # 验证是否是 Motion Photo
    if not is_motion_photo(data):
        raise ValueError(f"不是有效的 Motion Photo 文件: {motion_photo_path}")
    
    # 提取 JPEG 和 MP4
    logger.info("提取 JPEG...")
    jpeg_data = _extract_jpeg_from_motion_photo(data)
    logger.info("提取 MP4...")
    mp4_data = _extract_mp4_from_motion_photo(data)
    
    # 生成唯一的 ContentIdentifier
    content_identifier = str(uuid.uuid4()).upper()
    logger.info(f"ContentIdentifier: {content_identifier}")
    
    # 转换 MP4 为 MOV
    logger.info("转换为 QuickTime MOV...")
    mov_data = _convert_mp4_to_mov_with_metadata(mp4_data, content_identifier)
    
    # 保存文件
    output_name = motion_photo_path.stem
    jpeg_output = output_dir / f"{output_name}.jpg"
    mov_output = output_dir / f"{output_name}.mov"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    jpeg_output.write_bytes(jpeg_data)
    mov_output.write_bytes(mov_data)
    
    logger.info("转换完成:")
    logger.info(f"  JPEG: {jpeg_output}")
    logger.info(f"  MOV:  {mov_output}")
    logger.info(f"  大小: JPEG={len(jpeg_data):,} bytes, MOV={len(mov_data):,} bytes")
    
    return jpeg_output, mov_output