"""
build/eng-*.ttf と build/jp-*.ttf を fontTools で合成し、
OS/2, post, name テーブルを整えて dist/serein-*.ttf を書き出す。
"""

from pathlib import Path
from shutil import copyfile

from fontTools import merge
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
SOURCE_DIR = ROOT / "source"
LICENSE_PATH = ROOT / "LICENSE.txt"

FONT_NAME = "serein"
VERSION = "0.900"
VENDOR = "TWR"  # 任意のベンダー4文字コード

# style -> (subfamily名, bold?, italic?, fsSelectionビット, macStyleビット)
STYLES = {
    "Regular": {"subfamily": "Regular", "bold": False, "italic": False},
    "Bold": {"subfamily": "Bold", "bold": True, "italic": False},
    "Italic": {"subfamily": "Italic", "bold": False, "italic": True},
    "BoldItalic": {"subfamily": "Bold Italic", "bold": True, "italic": True},
}


def main():
    DIST_DIR.mkdir(exist_ok=True)
    copyfile(LICENSE_PATH, DIST_DIR / "LICENSE.txt")

    for style, meta in STYLES.items():
        print(f"=== merge {style} ===")
        eng_path = BUILD_DIR / f"eng-{style}.ttf"
        jp_path = BUILD_DIR / f"jp-{style}.ttf"

        # FontForge の TTF 出力で等幅化された結合文字を元の幅 0 に戻す。
        with TTFont(SOURCE_DIR / "CascadiaMono" / f"CascadiaMono-{style}.ttf") as source:
            with TTFont(eng_path) as eng_font:
                restore_zero_width_glyphs(eng_font, source)
                eng_font.save(eng_path)

        # 日本語フォント側の縦書き関連テーブルを削除しておく（merge時の衝突回避）
        jp_font = TTFont(str(jp_path))
        for tag in ("vhea", "vmtx"):
            if tag in jp_font:
                del jp_font[tag]
        jp_font.save(str(jp_path))

        merger = merge.Merger()
        merged = merger.merge([str(eng_path), str(jp_path)])

        fix_os2(merged, meta)
        fix_post(merged)
        fix_head(merged, meta)
        fix_name(merged, style, meta)

        out_path = DIST_DIR / f"{FONT_NAME}-{style}.ttf"
        merged.save(str(out_path))
        print(f"wrote {out_path}")


def restore_zero_width_glyphs(font, source):
    metrics = font["hmtx"].metrics
    source_metrics = source["hmtx"].metrics
    # cmap にない GSUB 用の結合字形も、名前が一致すれば復元する。
    zero_glyphs = {
        name for name, (width, _) in source_metrics.items()
        if width == 0 and name in metrics
    }
    cmap = font.getBestCmap()
    for cp, name in source.getBestCmap().items():
        if source_metrics[name][0] == 0 and cp in cmap:
            zero_glyphs.add(cmap[cp])
    for name in zero_glyphs:
        metrics[name] = (0, metrics[name][1])


def license_metadata():
    # 元フォントの著作権表示をそのまま収録する。本文は同梱ライセンスと共通。
    notices = []
    for family in ("CascadiaMono", "NotoSansJP"):
        text = (SOURCE_DIR / family / "OFL.txt").read_text(encoding="utf-8")
        notices.append(text.split("\n\n", 1)[0].strip())
    copyright_text = "\n\n".join(notices)
    text = LICENSE_PATH.read_text(encoding="utf-8")
    license_text = text[text.index("SIL OPEN FONT LICENSE Version 1.1"):].strip()
    return copyright_text, copyright_text + "\n\n" + license_text


def fix_os2(font, meta):
    os2 = font["OS/2"]

    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    zero_glyph = cmap.get(ord("0"))
    if zero_glyph:
        os2.xAvgCharWidth = hmtx[zero_glyph][0]

    # fsSelection: bit0=Italic, bit5=Bold, bit6=Regular
    fs = os2.fsSelection
    fs &= ~((1 << 0) | (1 << 5) | (1 << 6))
    if meta["italic"]:
        fs |= 1 << 0
    if meta["bold"]:
        fs |= 1 << 5
    if not meta["italic"] and not meta["bold"]:
        fs |= 1 << 6
    os2.fsSelection = fs

    os2.usWeightClass = 700 if meta["bold"] else 400
    os2.achVendID = VENDOR

    # PANOSE: 等幅であることを明示 (bProportion = 9)
    os2.panose.bProportion = 9


def fix_post(font):
    font["post"].isFixedPitch = 1


def fix_head(font, meta):
    head = font["head"]
    head.fontRevision = float(VERSION)
    mac_style = 0
    if meta["bold"]:
        mac_style |= 1 << 0
    if meta["italic"]:
        mac_style |= 1 << 1
    head.macStyle = mac_style


def fix_name(font, style, meta):
    name = font["name"]
    name.names = []

    family = FONT_NAME
    subfamily = meta["subfamily"]
    full_name = f"{family} {subfamily}"
    ps_name = f"{family}-{style}"
    unique_id = f"{VERSION};{VENDOR};{ps_name}"

    # RIBBI (Regular/Italic/Bold/Bold Italic) で正しくグルーピングされるよう、
    # Bold/Italic 系は nameID 1 に太さ・斜体を含めず nameID 16/17 (Preferred) を別途設定する。
    legacy_family = family
    legacy_subfamily = subfamily
    if meta["bold"] or meta["italic"]:
        # レガシーな family/subfamily は 4 パターンに正規化
        legacy_family = family
        legacy_subfamily = subfamily

    copyright_text, license_text = license_metadata()
    records = {
        0: copyright_text,
        1: legacy_family,
        2: legacy_subfamily,
        3: unique_id,
        4: full_name,
        5: f"Version {VERSION}",
        6: ps_name,
        13: license_text,
        14: "https://openfontlicense.org/open-font-license-official-text/",
        16: family,
        17: subfamily,
    }

    for name_id, value in records.items():
        name.setName(value, name_id, 3, 1, 0x409)  # Windows, Unicode BMP, en-US
        name.setName(value, name_id, 1, 0, 0)  # Mac, Roman, English


if __name__ == "__main__":
    main()
