#!fontforge --lang=py -script
"""
FontForge スクリプト（ffpython 経由で実行する）

Cascadia Mono（欧文・半角）と Noto Sans JP（和文・全角）を合成する準備として、
- 日本語フォントの em を Cascadia 側に合わせる
- Cascadia と重複するコードポイントを日本語フォント側から削除する
- 日本語グリフの幅を「半角 = Cascadia の半角幅」「全角 = その2倍」に揃える
- イタリック系は日本語グリフを疑似的に傾ける
を行い、スタイルごとに 2 つの中間 TTF（eng-*.ttf / jp-*.ttf）を書き出す。
最終的な合成（cmap 統合・OS/2, name テーブル調整）は 03_merge_fix.py（fontTools）で行う。
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fontforge
import psMat

from corner_round import round_glyph_corners

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT, "source")
BUILD_DIR = os.path.join(ROOT, "build")

FONT_NAME = "serein"

# 日本語グリフの角を丸める半径。em に対する比率で指定する（約6%＝「強め」）。
JP_CORNER_RADIUS_RATIO = 0.06

# eng_style, jp_style, 合成後スタイル名, イタリックか
STYLES = [
    ("Regular", "Regular", "Regular", False),
    ("Bold", "Bold", "Bold", False),
    ("Italic", "Regular", "Italic", True),
    ("BoldItalic", "Bold", "BoldItalic", True),
]


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)

    for eng_style, jp_style, merged_style, is_italic in STYLES:
        print(f"=== {merged_style} ===")
        generate_font(eng_style, jp_style, merged_style, is_italic)


def generate_font(eng_style, jp_style, merged_style, is_italic):
    eng_path = os.path.join(SOURCE_DIR, "CascadiaMono", f"CascadiaMono-{eng_style}.ttf")
    jp_path = os.path.join(SOURCE_DIR, "NotoSansJP", f"NotoSansJP-{jp_style}.ttf")

    eng_font = fontforge.open(eng_path)
    jp_font = fontforge.open(jp_path)

    unlink_references(eng_font)
    unlink_references(jp_font)

    # --- em を揃える ---
    eng_em = eng_font.em
    jp_font.em = eng_em

    # --- 半角・全角の目標幅 ---
    half_width = eng_font[0x0030].width  # Cascadia Mono の半角幅（'0' で代表させる）
    full_width = half_width * 2

    # --- Cascadia が既に持っているコードポイントは Noto 側から削除する ---
    remove_duplicate_glyphs(eng_font, jp_font)

    # --- 日本語グリフの幅を半角/全角ぴったりに揃える ---
    normalize_jp_widths(jp_font, eng_em, half_width, full_width)

    # --- ひらがな・カタカナ・漢字の角を少し丸める ---
    round_jp_corners(jp_font, eng_em)

    # --- イタリックは日本語グリフを疑似的に傾ける ---
    if is_italic:
        italic_angle = abs(eng_font.italicangle) or 10
        jp_font.italicangle = -italic_angle
        skew_glyphs(jp_font, italic_angle)

    # --- GPOS は日本語側に残すとトラブルの元なので削除（GSUB は残す） ---
    remove_gpos_lookups(jp_font)

    # --- post テーブルのグリフ名重複対策 ---
    dedupe_glyph_names(eng_font)
    dedupe_glyph_names(jp_font)

    # --- メタデータを揃える ---
    apply_metrics(eng_font, jp_font)
    set_names(eng_font, FONT_NAME, merged_style)
    set_names(jp_font, FONT_NAME, merged_style)

    eng_out = os.path.join(BUILD_DIR, f"eng-{merged_style}.ttf")
    jp_out = os.path.join(BUILD_DIR, f"jp-{merged_style}.ttf")
    eng_font.generate(eng_out)
    jp_font.generate(jp_out)

    eng_font.close()
    jp_font.close()


def unlink_references(font):
    for glyph in font.glyphs():
        if glyph.isWorthOutputting():
            font.selection.select(("more", None), glyph)
    font.unlinkReferences()
    font.selection.none()


def remove_duplicate_glyphs(eng_font, jp_font):
    eng_codepoints = {g.unicode for g in eng_font.glyphs() if g.unicode >= 0}
    for glyph in eng_font.glyphs():
        eng_codepoints.update(
            cp for cp, selector, _ in (glyph.altuni or ()) if selector == -1
        )

    for g in jp_font.glyphs():
        # 1 つの字形が複数の文字に対応する場合がある（例: U+2026 / U+22EF）。
        # 重複した割り当てだけを外し、Noto にしかない文字や異体字は残す。
        aliases = list(dict.fromkeys(g.altuni or ()))
        remaining = [
            entry for entry in aliases
            if entry[1] != -1 or entry[0] not in eng_codepoints
        ]
        if g.unicode in eng_codepoints:
            primary = next((entry for entry in remaining if entry[1] == -1), None)
            if primary is not None:
                g.unicode = primary[0]
                remaining.remove(primary)
            elif remaining:
                g.unicode = -1
            else:
                g.clear()
                continue
        g.altuni = tuple(remaining) or None


def normalize_jp_widths(jp_font, eng_em, half_width, full_width):
    # em を eng に合わせた直後の「自然な」半角・全角幅を基準に閾値を置く
    # （Noto Sans JP は元の em = 元の全角幅 なので、半角 ≈ eng_em/2、全角 ≈ eng_em になる）
    threshold = eng_em * 0.75
    for glyph in jp_font.glyphs():
        w = glyph.width
        if w <= 0:
            continue
        target = half_width if w < threshold else full_width
        if w == target:
            continue
        scale = target / w
        glyph.transform(psMat.scale(scale, 1))
        glyph.width = target


def round_jp_corners(jp_font, eng_em):
    radius = eng_em * JP_CORNER_RADIUS_RATIO
    for glyph in jp_font.glyphs():
        if glyph.isWorthOutputting():
            round_glyph_corners(glyph, radius)


def skew_glyphs(font, angle_deg):
    rad = math.radians(angle_deg)
    for glyph in font.glyphs():
        w = glyph.width
        if w <= 0:
            continue
        glyph.transform(psMat.skew(rad))
        # 傾けた分だけ見た目の中心がずれるので、幅の半分を目安に引き戻す
        shift = w * math.tan(rad) / 2
        glyph.transform(psMat.translate(-shift, 0))
        glyph.width = w


def remove_gpos_lookups(font):
    for lookup in list(font.gpos_lookups):
        font.removeLookup(lookup)


def dedupe_glyph_names(font):
    seen = set()
    for glyph in font.glyphs():
        if glyph.glyphname in seen:
            glyph.glyphname = f"{glyph.glyphname}_{glyph.encoding}"
        else:
            seen.add(glyph.glyphname)


def apply_metrics(eng_font, jp_font):
    for font in (eng_font, jp_font):
        font.ascent = eng_font.ascent
        font.descent = eng_font.descent
        font.os2_winascent = eng_font.os2_winascent
        font.os2_windescent = eng_font.os2_windescent
        font.os2_typoascent = eng_font.os2_typoascent
        font.os2_typodescent = eng_font.os2_typodescent
        font.os2_typolinegap = eng_font.os2_typolinegap
        font.hhea_ascent = eng_font.hhea_ascent
        font.hhea_descent = eng_font.hhea_descent
        font.hhea_linegap = eng_font.hhea_linegap
        # VSCode 等ターミナルで下端のグリフ (g, j 等) が見切れるのを防ぐ
        font.horizontalBaseline = None


def set_names(font, family, style):
    subfamily = style if style != "BoldItalic" else "Bold Italic"
    font.familyname = family
    font.fontname = f"{family}-{style}".replace(" ", "")
    font.fullname = f"{family} {subfamily}"
    font.appendSFNTName(0x409, 1, family)
    font.appendSFNTName(0x409, 2, subfamily)
    font.appendSFNTName(0x409, 4, f"{family} {subfamily}")
    font.appendSFNTName(0x409, 6, f"{family}-{style}".replace(" ", ""))


if __name__ == "__main__":
    main()
