# -*- coding: utf-8 -*-
"""assets/app.css 를 각 html 에 인라인으로 심는다.

CSS 를 고친 뒤 `python3 build.py` 를 실행하면 모든 화면에 반영된다.
각 html 은 단독으로 열어도 스타일이 깨지지 않는다 (메일 첨부, 드래그 열기 등).
"""
import pathlib, re

here = pathlib.Path(__file__).parent
css = (here / "assets" / "app.css").read_text(encoding="utf-8")
block = '<style data-src="assets/app.css">\n' + css + '\n</style>'
pat = re.compile(
    r'<link rel="stylesheet" href="assets/app\.css">|<style data-src="assets/app\.css">.*?</style>',
    re.S)

for f in sorted(here.glob("*.html")):
    src = f.read_text(encoding="utf-8")
    out, n = pat.subn(lambda _: block, src, count=1)
    if n:
        f.write_text(out, encoding="utf-8")
    print(f"{'✓' if n else '−'} {f.name}")
