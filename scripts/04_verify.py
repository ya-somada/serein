"""生成済みの全スタイルについて、文字欠落・幅・配布ライセンスを検証する。"""

from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
STYLES = {
    "Regular": "Regular",
    "Bold": "Bold",
    "Italic": "Regular",
    "BoldItalic": "Bold",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_style(style, jp_style):
    with (
        TTFont(ROOT / "dist" / f"serein-{style}.ttf", checkChecksums=2) as font,
        TTFont(ROOT / "source" / "CascadiaMono" / f"CascadiaMono-{style}.ttf") as eng,
        TTFont(ROOT / "source" / "NotoSansJP" / f"NotoSansJP-{jp_style}.ttf") as jp,
    ):
        font.ensureDecompiled()
        cmap = font.getBestCmap()
        eng_cmap = eng.getBestCmap()
        jp_cmap = jp.getBestCmap()
        missing = (set(eng_cmap) | set(jp_cmap)) - set(cmap)
        require(not missing, f"{style}: missing codepoints: {sorted(missing)}")

        metrics = font["hmtx"].metrics
        half_width = eng["hmtx"][eng_cmap[ord("0")]][0]
        for cp in (ord("0"), ord("A"), 0xFF76):
            require(metrics[cmap[cp]][0] == half_width, f"{style}: U+{cp:04X} half width")
        for cp in (0x3000, 0x3042, 0x30A2, 0x4E2D, 0xFF0F):
            require(metrics[cmap[cp]][0] == half_width * 2, f"{style}: U+{cp:04X} full width")
        for cp in (0xFF0F, 0x22EF):
            require(font["glyf"][cmap[cp]].numberOfContours != 0,
                    f"{style}: U+{cp:04X} has no outline")

        zero_count = 0
        for source, source_cmap in ((eng, eng_cmap), (jp, jp_cmap)):
            for cp, name in source_cmap.items():
                if source is jp and cp in eng_cmap:
                    continue  # 重複する文字は Cascadia 側を優先する。
                if source["hmtx"][name][0] == 0:
                    require(metrics[cmap[cp]][0] == 0,
                            f"{style}: U+{cp:04X} must have zero advance")
                    zero_count += 1

        name = font["name"]
        for platform, encoding, language in ((3, 1, 0x409), (1, 0, 0)):
            records = {}
            for name_id in (0, 1, 5, 13, 14):
                record = name.getName(name_id, platform, encoding, language)
                require(record is not None, f"{style}: missing name ID {name_id}")
                records[name_id] = record.toUnicode()
            require(records[1] == "serein", f"{style}: incorrect family name")
            require(records[5].startswith("Version "), f"{style}: missing version string")
            version = float(records[5].split(" ", 1)[1])
            require(abs(font["head"].fontRevision - version) < 1 / 65536,
                    f"{style}: head and name versions differ")
            for family in ("CascadiaMono", "NotoSansJP"):
                notice = (ROOT / "source" / family / "OFL.txt").read_text(
                    encoding="utf-8"
                ).split("\n\n", 1)[0].strip()
                require(notice in records[0] and notice in records[13],
                        f"{style}: missing {family} copyright")
            license_file = (ROOT / "LICENSE.txt").read_text(encoding="utf-8")
            body = license_file[license_file.index("SIL OPEN FONT LICENSE Version 1.1"):].strip()
            require(body in records[13], f"{style}: missing full OFL text")
            require(records[14] == "https://openfontlicense.org/open-font-license-official-text/",
                    f"{style}: incorrect license URL")

        print(f"{style}: OK ({len(cmap)} codepoints, {zero_count} zero-width mappings, license)")


def main():
    require((ROOT / "dist" / "LICENSE.txt").read_bytes() == (ROOT / "LICENSE.txt").read_bytes(),
            "dist/LICENSE.txt must match LICENSE.txt")
    for style, jp_style in STYLES.items():
        verify_style(style, jp_style)


if __name__ == "__main__":
    main()
