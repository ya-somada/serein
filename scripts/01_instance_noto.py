"""
Noto Sans JP の可変フォント (NotoSansJP[wght].ttf) から
Regular (400) / Bold (700) の静的インスタンスを書き出す。
"""

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

SRC = Path(__file__).resolve().parent.parent / "source" / "NotoSansJP" / "NotoSansJP-VF.ttf"
OUT_DIR = SRC.parent

INSTANCES = {
    "Regular": 400,
    "Bold": 700,
}


def main():
    for style, wght in INSTANCES.items():
        font = TTFont(str(SRC))
        instantiateVariableFont(font, {"wght": wght}, inplace=True)
        out_path = OUT_DIR / f"NotoSansJP-{style}.ttf"
        font.save(str(out_path))
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
