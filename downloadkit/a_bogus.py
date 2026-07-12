"""
a_bogus 签名生成器（纯 Python 实现）

基于深度逆向的完整 a_bogus 算法，含浏览器指纹、SM3 哈希、RC4 加密、
自定义 Base64 编码和 XOR 校验。

参考实现：
  - Johnserf-Seed/f2: https://github.com/Johnserf-Seed/f2 (Apache 2.0)
  - JoeanAmier/TikTokDownloader (GPL-3.0)
"""

import time
import random
from typing import Optional, List, Union
from urllib.parse import urlparse, parse_qs, urlencode


# ============================================================
# 工具函数
# ============================================================

def _list_from_bytes(b: bytes) -> list[int]:
    return list(b)


def _sm3_hash_bytes(data: Union[str, bytes, List[int]]) -> List[int]:
    """SM3 哈希，返回 bytes list"""
    from gmssl import func
    from gmssl.sm3 import sm3_hash

    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    elif isinstance(data, bytes):
        data_bytes = data
    elif isinstance(data, list):
        data_bytes = bytes(data)
    else:
        raise TypeError(f"Unsupported type: {type(data)}")

    hex_result = sm3_hash(func.bytes_to_list(data_bytes))
    return [int(hex_result[i:i+2], 16) for i in range(0, len(hex_result), 2)]


def _rc4_encrypt(key: bytes, data: str) -> bytes:
    """RC4 加密"""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]

    i = j = 0
    output = []
    for char in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        K = S[(S[i] + S[j]) % 256]
        output.append(ord(char) ^ K)
    return bytes(output)


def _js_shift_right(val: int, n: int) -> int:
    """JavaScript 风格的 >> (无符号 32 位)"""
    return (val % 0x100000000) >> n


def _generate_random_string(length: int = 3) -> str:
    """生成随机字节序列（模拟 JS 的随机字节生成）"""
    _rd = int(random.random() * 10000)
    result = []
    for _ in range(length):
        result.extend([
            chr(((_rd & 255) & 170) | 1),
            chr(((_rd & 255) & 85) | 2),
            chr((_js_shift_right(_rd, 8) & 170) | 5),
            chr((_js_shift_right(_rd, 8) & 85) | 40),
        ])
    return "".join(result)


def _generate_browser_fingerprint(browser: str = "Edge") -> str:
    """生成浏览器指纹字符串"""
    inner_w = random.randint(1024, 1920)
    inner_h = random.randint(768, 1080)
    outer_w = inner_w + random.randint(24, 32)
    outer_h = inner_h + random.randint(75, 90)
    screen_x = 0
    screen_y = random.choice([0, 30])
    size_w = random.randint(1024, 1920)
    size_h = random.randint(768, 1080)
    avail_w = random.randint(1280, 1920)
    avail_h = random.randint(800, 1080)
    platform = "Win32"
    color_depth = "24"
    pixel_depth = "24"

    return (
        f"{inner_w}|{inner_h}|{outer_w}|{outer_h}|"
        f"{screen_x}|{screen_y}|0|0|{size_w}|{size_h}|"
        f"{avail_w}|{avail_h}|{inner_w}|{inner_h}|"
        f"{color_depth}|{pixel_depth}|{platform}"
    )


# ============================================================
# 主类
# ============================================================

class ABogusGenerator:
    """a_bogus 签名生成器"""

    # 排序索引（44 个位置）
    SORT_INDEX = [
        18, 20, 52, 26, 30, 34, 58, 38, 40, 53, 42, 21, 27, 54, 55,
        31, 35, 57, 39, 41, 43, 22, 28, 32, 60, 36, 23, 29, 33, 37,
        44, 45, 59, 46, 47, 48, 49, 50, 24, 25, 65, 66, 70, 71
    ]

    SORT_INDEX_2 = [
        18, 20, 26, 30, 34, 38, 40, 42, 21, 27, 31, 35, 39, 41, 43,
        22, 28, 32, 36, 23, 29, 33, 37, 44, 45, 46, 47, 48, 49, 50,
        24, 25, 52, 53, 54, 55, 57, 58, 59, 60, 65, 66, 70, 71
    ]

    # 自定义 Base64 字符表
    BASE64_CHARS = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
    BASE64_CHARS_2 = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"

    # 大数组（用于 transform_bytes）
    BIG_ARRAY = [
        121, 243, 55, 234, 103, 36, 47, 228, 30, 231, 106, 6, 115, 95, 78, 101,
        250, 207, 198, 50, 139, 227, 220, 105, 97, 143, 34, 28, 194, 215, 18, 100,
        159, 160, 43, 8, 169, 217, 180, 120, 247, 45, 90, 11, 27, 197, 46, 3,
        84, 72, 5, 68, 62, 56, 221, 75, 144, 79, 73, 161, 178, 81, 64, 187,
        134, 117, 186, 118, 16, 241, 130, 71, 89, 147, 122, 129, 65, 40, 88, 150,
        110, 219, 199, 255, 181, 254, 48, 4, 195, 248, 208, 32, 116, 167, 69, 201,
        17, 124, 125, 104, 96, 83, 80, 127, 236, 108, 154, 126, 204, 15, 20, 135,
        112, 158, 13, 1, 188, 164, 210, 237, 222, 98, 212, 77, 253, 42, 170, 202,
        26, 22, 29, 182, 251, 10, 173, 152, 58, 138, 54, 141, 185, 33, 157, 31,
        252, 132, 233, 235, 102, 196, 191, 223, 240, 148, 39, 123, 92, 82, 128, 109,
        57, 24, 38, 113, 209, 245, 2, 119, 153, 229, 189, 214, 230, 174, 232, 63,
        52, 205, 86, 140, 66, 175, 111, 171, 246, 133, 238, 193, 99, 60, 74, 91,
        225, 51, 76, 37, 145, 211, 166, 151, 213, 206, 0, 200, 244, 176, 218, 44,
        184, 172, 49, 216, 93, 168, 53, 21, 183, 41, 67, 85, 224, 155, 226, 242,
        87, 177, 146, 70, 190, 12, 162, 19, 137, 114, 25, 165, 163, 192, 23, 59,
        9, 94, 179, 107, 35, 7, 142, 131, 239, 203, 149, 136, 61, 249, 14, 156
    ]

    def __init__(
        self,
        user_agent: str = "",
        browser_fp: str = "",
        aid: int = 6383,
        page_id: int = 0,
        options: Optional[List[int]] = None,
        salt: str = "cus",
    ):
        self.aid = aid
        self.page_id = page_id
        self.salt = salt
        self.options = options or [0, 1, 14]  # GET: [0,1,8], POST: [0,1,14]

        self.user_agent = (
            user_agent or
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.browser_fp = browser_fp or _generate_browser_fingerprint("Edge")

    def _transform_bytes(self, bytes_list: List[int]) -> str:
        """对字节数组进行变换（使用大数组）"""
        arr = list(self.BIG_ARRAY)  # 拷贝，方法内会修改
        result = []
        idx_b = arr[1]
        initial = 0
        for idx, val in enumerate(bytes_list):
            if idx == 0:
                initial = arr[idx_b]
                s = idx_b + initial
                arr[1] = initial
                arr[idx_b] = idx_b
            else:
                s = initial + val_e

            s %= len(arr)
            val_f = arr[s]
            result.append(val ^ val_f)
            val_e = arr[(idx + 2) % len(arr)]
            s = (idx_b + val_e) % len(arr)
            initial = arr[s]
            arr[s] = arr[(idx + 2) % len(arr)]
            arr[(idx + 2) % len(arr)] = initial
            idx_b = s

        return "".join(chr(v) for v in result)

    def _encode_base64(self, data: str, table_idx: int = 0) -> str:
        """标准 Base64 编码（使用自定义字符表）"""
        alphabet = self.BASE64_CHARS if table_idx == 0 else self.BASE64_CHARS_2
        binary = "".join(f"{ord(c):08b}" for c in data)
        pad = (6 - len(binary) % 6) % 6
        binary += "0" * pad
        indices = [int(binary[i:i+6], 2) for i in range(0, len(binary), 6)]
        result = "".join(alphabet[j] for j in indices)
        result += "=" * (pad // 2)
        return result

    def _encode_abogus(self, data: str, table_idx: int = 0) -> str:
        """a_bogus 专用编码（3 字节 → 4 字符）"""
        alphabet = self.BASE64_CHARS if table_idx == 0 else self.BASE64_CHARS_2
        result = []
        i = 0
        while i < len(data):
            # 取 3 个字节组成 24 位整数
            if i + 2 < len(data):
                n = (ord(data[i]) << 16) | (ord(data[i+1]) << 8) | ord(data[i+2])
            elif i + 1 < len(data):
                n = (ord(data[i]) << 16) | (ord(data[i+1]) << 8)
            else:
                n = ord(data[i]) << 16

            # 拆成 4 个 6 位值
            shifts = [18, 12, 6, 0]
            masks = [0xFC0000, 0x03F000, 0x0FC0, 0x3F]
            for s, m in zip(shifts, masks):
                if s == 6 and i + 1 >= len(data):
                    break
                if s == 0 and i + 2 >= len(data):
                    break
                result.append(alphabet[(n & m) >> s])

            i += 3

        # 填充 =
        pad = (4 - len(result) % 4) % 4
        result.append("=" * pad)
        return "".join(result)

    def generate(self, params: str, body: str = "") -> str:
        """生成 a_bogus 签名

        Args:
            params: URL 查询参数字符串（如 "a=1&b=2"）
            body: POST body（GET 请求传空字符串）

        Returns:
            a_bogus 签名字符串
        """
        start_time = int(time.time() * 1000)

        # ===== 3 次 SM3 哈希 =====
        # 1) params hash: SM3(SM3(params + salt))
        params_hash = _sm3_hash_bytes(_sm3_hash_bytes(params + self.salt))

        # 2) body hash: SM3(SM3(body + salt))
        body_hash = _sm3_hash_bytes(_sm3_hash_bytes(body + self.salt))

        # 3) UA hash: SM3(Base64(RC4(ua_key, ua)))
        ua_key = bytes([0x00, 0x01, 0x0E])
        rc4_ua = _rc4_encrypt(ua_key, self.user_agent)
        rc4_ua_str = "".join(chr(b) for b in rc4_ua)
        ua_b64 = self._encode_base64(rc4_ua_str, 1)
        ua_hash = _sm3_hash_bytes(ua_b64)

        end_time = int(time.time() * 1000)

        # ===== 构造 ab_dir =====
        ab_dir: dict = {
            8: 3,
            15: {
                "aid": self.aid,
                "pageId": self.page_id,
                "boe": False,
                "ddrt": 8.5,
                "paths": [
                    "^/webcast/", "^/aweme/v1/", "^/aweme/v2/",
                    "/v1/message/send", "^/live/", "^/captcha/", "^/ecom/",
                ],
                "track": {"mode": 0, "delay": 300, "paths": []},
                "dump": True,
                "rpU": "",
            },
            18: 44,
            19: [1, 0, 1, 0, 1],
            66: 0,
            69: 0,
            70: 0,
            71: 0,
        }

        # 时间戳（开始）
        ab_dir[20] = (start_time >> 24) & 255
        ab_dir[21] = (start_time >> 16) & 255
        ab_dir[22] = (start_time >> 8) & 255
        ab_dir[23] = start_time & 255
        ab_dir[24] = (start_time // 256 // 256 // 256 // 256) >> 0
        ab_dir[25] = (start_time // 256 // 256 // 256 // 256 // 256) >> 0

        # Options
        ab_dir[26] = (self.options[0] >> 24) & 255
        ab_dir[27] = (self.options[0] >> 16) & 255
        ab_dir[28] = (self.options[0] >> 8) & 255
        ab_dir[29] = self.options[0] & 255

        ab_dir[30] = (self.options[1] // 256) & 255
        ab_dir[31] = (self.options[1] % 256) & 255
        ab_dir[32] = (self.options[1] >> 24) & 255
        ab_dir[33] = (self.options[1] >> 16) & 255

        ab_dir[34] = (self.options[2] >> 24) & 255
        ab_dir[35] = (self.options[2] >> 16) & 255
        ab_dir[36] = (self.options[2] >> 8) & 255
        ab_dir[37] = self.options[2] & 255

        # 哈希值（特定位置）
        ab_dir[38] = params_hash[21]
        ab_dir[39] = params_hash[22]
        ab_dir[40] = body_hash[21]
        ab_dir[41] = body_hash[22]
        ab_dir[42] = ua_hash[23]
        ab_dir[43] = ua_hash[24]

        # 时间戳（结束）
        ab_dir[44] = (end_time >> 24) & 255
        ab_dir[45] = (end_time >> 16) & 255
        ab_dir[46] = (end_time >> 8) & 255
        ab_dir[47] = end_time & 255
        ab_dir[48] = ab_dir[8]
        ab_dir[49] = (end_time // 256 // 256 // 256 // 256) >> 0
        ab_dir[50] = (end_time // 256 // 256 // 256 // 256 // 256) >> 0

        # pageId & aid
        ab_dir[51] = (self.page_id >> 24) & 255
        ab_dir[52] = (self.page_id >> 16) & 255
        ab_dir[53] = (self.page_id >> 8) & 255
        ab_dir[54] = self.page_id & 255
        ab_dir[55] = self.page_id
        ab_dir[56] = self.aid
        ab_dir[57] = self.aid & 255
        ab_dir[58] = (self.aid >> 8) & 255
        ab_dir[59] = (self.aid >> 16) & 255
        ab_dir[60] = (self.aid >> 24) & 255

        # 浏览器指纹长度
        ab_dir[64] = len(self.browser_fp)
        ab_dir[65] = len(self.browser_fp)

        # ===== 排序取值 =====
        sorted_values = [ab_dir.get(i, 0) for i in self.SORT_INDEX]

        # 浏览器指纹 ASCII
        fp_ascii = [ord(c) for c in self.browser_fp]

        # ===== XOR 校验 =====
        xor_val = (len(self.browser_fp) & 255) >> 8 & 255
        for idx in range(len(self.SORT_INDEX_2) - 1):
            if idx == 0:
                xor_val = ab_dir.get(self.SORT_INDEX_2[idx], 0)
            xor_val ^= ab_dir.get(self.SORT_INDEX_2[idx + 1], 0)

        # 拼装最终字节数组
        sorted_values.extend(fp_ascii)
        sorted_values.append(xor_val)

        # ===== RC4 变换 + 自定义 Base64 编码 =====
        # 1) 生成随机前导
        prefix = _generate_random_string()

        # 2) 变换
        transformed = self._transform_bytes(sorted_values)

        # 3) 拼接
        final_str = prefix + transformed

        # 4) 编码
        a_bogus = self._encode_abogus(final_str, 0)

        return a_bogus


# ============================================================
# 便捷接口
# ============================================================

def add_a_bogus_to_url(
    url: str,
    user_agent: str,
    cookie_str: str = "",
) -> str:
    """为 API URL 追加 a_bogus 签名参数"""
    parsed = urlparse(url)
    params_str = parsed.query

    generator = ABogusGenerator(user_agent=user_agent)
    a_bogus = generator.generate(params_str, body="")

    separator = "&" if params_str else "?"
    return f"{url}{separator}a_bogus={a_bogus}"


def generate_a_bogus(
    url: str,
    user_agent: str,
    cookie_str: str = "",
) -> str:
    """生成 a_bogus 签名值（不含 URL 拼接）"""
    parsed = urlparse(url)
    params_str = parsed.query
    generator = ABogusGenerator(user_agent=user_agent)
    return generator.generate(params_str, body="")


def build_a_bogus_params(
    base_params: dict,
    user_agent: str,
    cookie_str: str = "",
) -> dict:
    """构建包含 a_bogus 签名的完整参数字典"""
    import random
    import string

    if "msToken" not in base_params:
        rand = random.Random()
        chars = string.ascii_letters + string.digits + '-_'
        base_params["msToken"] = ''.join(rand.choices(chars, k=126)) + "=="

    params_str = urlencode(base_params)
    generator = ABogusGenerator(user_agent=user_agent)
    a_bogus = generator.generate(params_str, body="")

    result = dict(base_params)
    result["a_bogus"] = a_bogus
    return result
