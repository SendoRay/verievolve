"""为中期报告图统一注册标准简体中文字体。"""

import tempfile
from pathlib import Path

from matplotlib import font_manager


SIMPLIFIED_CHINESE_FONTS = [
    "PingFang SC",
    "Noto Sans CJK SC",
    "Microsoft YaHei",
    "Hiragino Sans GB",
    "DejaVu Sans",
]


def _font_names(font, name_id):
    names = set()
    for record in font["name"].names:
        if record.nameID == name_id:
            try:
                names.add(record.toUnicode())
            except Exception:
                pass
    return names


def _extract_pingfang_sc(ttc_path, cache_dir):
    """从 macOS 的 PingFang.ttc 中抽出 Matplotlib 可识别的 SC 字面。"""
    try:
        from fontTools.ttLib import TTCollection
    except ImportError:
        return []

    outputs = []
    collection = TTCollection(str(ttc_path))
    wanted = {"Regular", "Medium", "Semibold"}
    for font in collection.fonts:
        if "PingFang SC" not in (_font_names(font, 1) | _font_names(font, 16)):
            continue
        subfamilies = _font_names(font, 2) | _font_names(font, 17)
        style = next((name for name in wanted if name in subfamilies), None)
        if style is None:
            continue
        output = cache_dir / f"PingFangSC-{style}.ttf"
        if not output.is_file() or output.stat().st_mtime < ttc_path.stat().st_mtime:
            font.save(output)
        outputs.append(output)
    return outputs


def register_simplified_chinese_fonts():
    """注册 PingFang SC；其他系统注册其明确的简体中文回退字体。"""
    font_files = []
    pingfang_collections = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        *sorted(
            Path("/System/Library/AssetsV2").glob(
                "com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc"
            )
        ),
    ]
    cache_dir = Path(tempfile.gettempdir()) / "verievolve-matplotlib-fonts"
    for collection in pingfang_collections:
        if collection.is_file():
            cache_dir.mkdir(parents=True, exist_ok=True)
            font_files.extend(_extract_pingfang_sc(collection, cache_dir))
            break

    font_files.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        ]
    )
    for font_file in font_files:
        if font_file.is_file():
            font_manager.fontManager.addfont(str(font_file))
