"""Font discovery and loading utilities"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Union

from fontTools.ttLib import TTCollection, TTFont
from PIL import ImageFont

from videocaptioner.config import FONTS_PATH
from videocaptioner.core.utils.logger import setup_logger

FontType = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]

logger = setup_logger("subtitle.font")


def _get_font_family_name(font_path: Path, font_index: int = 0) -> Optional[str]:
    """Extract font family name from font file (cross-platform)"""
    try:
        font = TTFont(str(font_path), fontNumber=font_index)
        name_table = font.get("name")
        if not name_table:
            return None

        # nameID 16: Typographic Family (preferred)
        # nameID 1: Font Family (fallback)
        for name_id in [16, 1]:
            for record in name_table.names:
                if record.nameID == name_id and record.platformID == 3:
                    try:
                        family_name = record.toUnicode()
                        return family_name.split(",")[0].strip()
                    except Exception:
                        continue

        for name_id in [16, 1]:
            for record in name_table.names:
                if record.nameID == name_id:
                    try:
                        family_name = record.toUnicode()
                        return family_name.split(",")[0].strip()
                    except Exception:
                        continue

        return None
    except Exception as e:
        logger.debug(f"Failed to parse font {font_path.name} (index={font_index}): {e}")
        return None


@lru_cache(maxsize=1)
def get_builtin_fonts() -> tuple[Dict[str, str], ...]:
    """Get built-in fonts list with actual family names"""
    builtin_fonts = []

    if FONTS_PATH.exists():
        for font_file in FONTS_PATH.glob("*.[ot]tf*"):
            family_name = _get_font_family_name(font_file)
            if family_name:
                builtin_fonts.append({"name": family_name, "path": str(font_file)})
                logger.debug(f"Built-in font: {font_file.name} -> {family_name}")
            else:
                display_name = font_file.stem
                builtin_fonts.append({"name": display_name, "path": str(font_file)})
                logger.debug(
                    f"Cannot get family name for {font_file.name}, using filename"
                )

    return tuple(builtin_fonts)


@lru_cache(maxsize=1)
def get_system_fonts() -> tuple[Dict[str, str], ...]:
    """Return installed Windows fonts with their real file paths.

    Pillow cannot reliably load a Windows font by family name alone (for
    example ``Microsoft YaHei``). Keeping the path lets the rounded subtitle
    renderer use the same system font that ASS/libass resolves by family name.
    """
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not fonts_dir.is_dir():
        return ()

    fonts: dict[str, str] = {}
    for font_file in fonts_dir.iterdir():
        if font_file.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
            continue
        family_name = _get_font_family_name(font_file)
        if family_name and family_name not in fonts:
            fonts[family_name] = str(font_file)

    return tuple({"name": name, "path": path} for name, path in sorted(fonts.items()))


def _get_font_style_name(font_path: Path, font_index: int = 0) -> Optional[str]:
    """Extract the subfamily/style name from a font face."""
    try:
        font = TTFont(str(font_path), fontNumber=font_index)
        name_table = font.get("name")
        if not name_table:
            return None
        for name_id in (17, 2):  # Typographic Subfamily, then Subfamily
            for record in name_table.names:
                if record.nameID == name_id:
                    try:
                        return record.toUnicode().strip()
                    except Exception:
                        continue
    except Exception as e:
        logger.debug(f"Failed to parse style {font_path.name} (index={font_index}): {e}")
    return None


def _iter_font_faces(font_path: Path):
    """Yield (font index, family, style) for every face in a font file."""
    try:
        if font_path.suffix.lower() == ".ttc":
            collection = TTCollection(str(font_path), lazy=True)
            indices = range(len(collection.fonts))
        else:
            indices = (0,)
        for index in indices:
            family = _get_font_family_name(font_path, index)
            if family:
                yield index, family, _get_font_style_name(font_path, index) or "Regular"
    except Exception as e:
        logger.debug(f"Failed to enumerate font faces in {font_path.name}: {e}")


@lru_cache(maxsize=1)
def get_font_variants() -> tuple[Dict[str, object], ...]:
    """Return selectable font faces, including bold/italic variants."""
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    files = []
    for root in (FONTS_PATH, fonts_dir):
        if root.is_dir():
            files.extend(
                path
                for path in root.iterdir()
                if path.suffix.lower() in {".ttf", ".otf", ".ttc"}
            )

    variants = []
    seen = set()
    for font_path in files:
        for font_index, family, style in _iter_font_faces(font_path):
            display_name = f"{family} / {style}"
            key = display_name.casefold()
            if key in seen:
                continue
            seen.add(key)
            variants.append(
                {
                    "name": display_name,
                    "family_name": family,
                    "style_name": style,
                    "path": str(font_path),
                    "font_index": font_index,
                }
            )

    return tuple(sorted(variants, key=lambda item: str(item["name"]).casefold()))


@lru_cache(maxsize=512)
def _find_font_record(font_name: str) -> Optional[Dict[str, object]]:
    """Resolve a configured family or variant to its local font face."""
    for font in get_font_variants():
        if font["name"] == font_name:
            return font
    for font in get_builtin_fonts():
        if font["name"] == font_name:
            return {**font, "family_name": font["name"], "font_index": 0}
    for font in get_system_fonts():
        if font["name"] == font_name:
            return {**font, "family_name": font["name"], "font_index": 0}
    path = Path(font_name)
    if path.is_file():
        return {"name": font_name, "family_name": font_name, "path": str(path), "font_index": 0}
    return None


@lru_cache(maxsize=512)
def font_supports_text(font_name: str, text: str) -> bool:
    """Return whether a named font contains glyphs for all visible characters."""
    if not text.strip():
        return True

    record = _find_font_record(font_name)
    if not record:
        return False

    try:
        font = TTFont(
            str(record["path"]),
            fontNumber=int(record.get("font_index", 0)),
            lazy=True,
        )
        cmap = font.getBestCmap() or {}
        return all(char.isspace() or ord(char) in cmap for char in text)
    except Exception as e:
        logger.debug(f"Failed to inspect glyph coverage for '{font_name}': {e}")
        return False


def get_font_ass_attributes(font_name: str) -> tuple[str, int, int]:
    """Return ASS family name, bold flag and italic flag for a selected face."""
    record = _find_font_record(font_name)
    if not record:
        return font_name, -1, 0

    family = str(record.get("family_name") or font_name)
    style = str(record.get("style_name") or "").casefold()
    is_variant = "/" in font_name
    if not is_variant:
        return family, -1, 0

    bold_terms = ("black", "heavy", "bold", "semibold", "demibold", "medium")
    italic_terms = ("italic", "oblique")
    return (
        family,
        -1 if any(term in style for term in bold_terms) else 0,
        -1 if any(term in style for term in italic_terms) else 0,
    )

@lru_cache(maxsize=64)
def get_font(size: int, font_name: str = "") -> FontType:
    """Get font object (built-in fonts first, then system fonts)"""
    if font_name:
        record = _find_font_record(font_name)
        if record:
            try:
                font = ImageFont.truetype(
                    str(record["path"]), size, index=int(record.get("font_index", 0))
                )
                logger.debug(f"Loaded local font: '{font_name}'")
                return font
            except Exception as e:
                logger.warning(f"Failed to load local font '{font_name}': {e}")

        try:
            font = ImageFont.truetype(font_name, size)
            logger.debug(f"Loaded system font: '{font_name}'")
            return font
        except (OSError, IOError):
            logger.warning(f"Cannot load font '{font_name}', using fallback")

    fallback_fonts = [f["name"] for f in get_builtin_fonts()]
    fallback_fonts.extend(font["path"] for font in get_system_fonts())
    fallback_fonts.extend(["PingFang SC", "Hiragino Sans GB", "Arial", "Helvetica"])

    for fallback in fallback_fonts:
        try:
            font = ImageFont.truetype(fallback, size)
            logger.debug(f"Using fallback font: '{fallback}'")
            return font
        except Exception:
            continue

    logger.warning("All fallback fonts failed, using default")
    return ImageFont.load_default()


@lru_cache(maxsize=128)
def get_ass_to_pil_ratio(font_name: str) -> float:
    """
    Get ASS to PIL font size conversion ratio

    ASS uses Windows line height (usWinAscent + usWinDescent),
    PIL uses em square (unitsPerEm).

    For Noto Sans SC: ratio = 1.448
    This means: PIL_size = ASS_size / 1.448

    Returns:
        Conversion ratio (typically 1.4-1.5 for CJK fonts)
    """
    # Find font file
    font_path = None
    record = _find_font_record(font_name)
    if record:
        font_path = Path(str(record["path"]))
        font_index = int(record.get("font_index", 0))
    else:
        font_index = 0

    for ext in [".ttf", ".otf", ".ttc"]:
        if font_path:
            break
        candidates = list(FONTS_PATH.glob(f"**/{font_name}*{ext}"))
        if candidates:
            font_path = candidates[0]
            break

    if not font_path:
        candidates = list(FONTS_PATH.glob(f"**/*{font_name}*"))
        if candidates:
            font_path = candidates[0]

    # Default ratio for most CJK fonts
    if not font_path:
        logger.debug(f"Font file not found: {font_name}, using default ratio 1.448")
        return 1.448

    try:
        font = TTFont(str(font_path), fontNumber=font_index)
        units_per_em = font["head"].unitsPerEm  # type: ignore
        win_ascent = font["OS/2"].usWinAscent  # type: ignore
        win_descent = font["OS/2"].usWinDescent  # type: ignore
        ratio = (win_ascent + win_descent) / units_per_em
        logger.debug(f"Font metrics for {font_name}: ratio={ratio:.3f}")
        return ratio
    except Exception as e:
        logger.warning(f"Failed to read font metrics for {font_name}: {e}")
        return 1.448


def clear_font_cache():
    """Clear font cache"""
    get_builtin_fonts.cache_clear()
    get_system_fonts.cache_clear()
    get_font_variants.cache_clear()
    _find_font_record.cache_clear()
    font_supports_text.cache_clear()
    get_font.cache_clear()
    get_ass_to_pil_ratio.cache_clear()
    logger.debug("Font cache cleared")
