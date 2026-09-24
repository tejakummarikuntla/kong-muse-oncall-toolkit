#!/usr/bin/env python3
"""
Composite the real Kong mark into a mascot SVG's `kong-slot`, and build a
contact sheet so the candidates can be judged visually rather than from source.

The characters are original artwork generated for this post. The Kong mark is
the real one, injected here rather than drawn, so the logo is never
approximated.

    python3 mascot.py sheet            # render all candidates side by side
    python3 mascot.py one <key>        # render one at 400px
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
CANDIDATES = HERE / "mascot-candidates.json"

# Kong mark only (no wordmark), viewBox 0 0 45 40.
KONG_MARK = (
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M13.5449 34.3219L14.6552 32.9579H22.7757L27.0263 38.2235L26.2967 39.9999H15.7654L16.0191 38.2235L13.5449 34.3219Z" fill="#159ECB"/>'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M16.5898 16.0508L20.3963 9.3894H24.8055L44.6628 32.8628L43.1085 40H34.6073L35.1466 38.0016L16.5898 16.0508Z" fill="#0EB399"/>'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M21.126 7.70816L22.9341 4.37747L28.2632 0L37.4622 7.26407L36.2886 8.50118L37.8746 10.7216V13.1324L33.3068 16.8755L25.5986 7.70816H21.126Z" fill="#3DB664"/>'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M6.59794 22.9341H9.10389L15.5749 17.383L24.1396 27.5654L21.7288 31.3084H13.7986L8.34259 38.3822L7.10547 39.9999H0V31.3084L6.59794 22.9341Z" fill="#17BDCB"/>'
)

# The agents were told to size the slot for a 127x40 wordmark. The mark alone is
# 45 wide, so centre it on that footprint to land where they planned it.
KONG_IN_SLOT = f'<g transform="translate(41,0)">{KONG_MARK}</g>'


def inject(svg: str) -> str:
    """Fill the empty <g id="kong-slot"> with the real Kong mark."""
    # Self-closing form.
    svg2, n = re.subn(
        r'(<g\b[^>]*\bid="kong-slot"[^>]*?)\s*/>',
        lambda m: m.group(1) + ">" + KONG_IN_SLOT + "</g>",
        svg,
        count=1,
    )
    if n:
        return svg2
    # Open/close form, possibly with whitespace between.
    svg2, n = re.subn(
        r'(<g\b[^>]*\bid="kong-slot"[^>]*>)\s*(</g>)',
        lambda m: m.group(1) + KONG_IN_SLOT + m.group(2),
        svg,
        count=1,
    )
    return svg2 if n else svg


def has_slot(svg: str) -> bool:
    return 'id="kong-slot"' in svg


def load():
    if not CANDIDATES.exists():
        sys.exit(f"no candidates at {CANDIDATES}")
    return json.loads(CANDIDATES.read_text())


PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@500;700&family=JetBrains+Mono:wght@500&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    width:{W}px; background:#08080c; color:#e7e9ee;
    font-family:'Inter',system-ui,sans-serif; padding:30px;
    display:flex; flex-wrap:wrap; gap:22px; align-content:flex-start;
  }}
  .card {{
    width:{CW}px; background:rgba(255,255,255,.022);
    border:1px solid rgba(255,255,255,.08); border-radius:12px;
    padding:16px; text-align:center;
  }}
  .art {{ height:{AH}px; display:flex; align-items:center; justify-content:center; gap:16px; }}
  .art svg {{ display:block; }}
  .big {{ width:{BIG}px; height:{BIG}px; }}
  .sml {{ width:72px; height:72px; }}
  .key {{
    font-family:'JetBrains Mono',monospace; font-size:11px; color:#ffb020;
    margin-top:12px; letter-spacing:.4px;
  }}
  .nm {{ font-size:13px; font-weight:700; margin-top:3px; }}
  .slot {{ font-size:10px; margin-top:6px; }}
  .yes {{ color:#3ddc97; }} .no {{ color:#ff5f5f; }}
</style>
{cards}
"""

CARD = """<div class="card">
  <div class="art">
    <span class="big">{svg_big}</span>
    <span class="sml">{svg_sml}</span>
  </div>
  <div class="key">{key}</div>
  <div class="nm">{name}</div>
  <div class="slot {cls}">{slot}</div>
</div>"""


def sheet():
    data = load()
    cards = []
    for m in data:
        svg = inject(m["svg"])
        ok = has_slot(m["svg"])
        cards.append(CARD.format(
            svg_big=svg, svg_sml=svg,
            key=m.get("key", "?"), name=m.get("name", ""),
            cls="yes" if ok else "no",
            slot="kong-slot found" if ok else "NO kong-slot in output",
        ))
    cols = 3
    cw = 300
    w = cols * cw + (cols - 1) * 22 + 60
    out = HERE / "mascot-sheet.html"
    out.write_text(PAGE.format(W=w, CW=cw, AH=210, BIG=170, cards="\n".join(cards)))
    print(f"  wrote {out.name}  ({len(data)} candidates, {w}px wide)")
    return w, ((len(data) + cols - 1) // cols) * 300 + 60


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sheet"
    if cmd == "sheet":
        w, h = sheet()
        print(f"  render at {w}x{h}")
    elif cmd == "one":
        key = sys.argv[2]
        m = next(x for x in load() if x.get("key") == key)
        svg = inject(m["svg"])
        out = HERE / f"mascot-{key}.html"
        out.write_text(
            f'<!doctype html><meta charset="utf-8">'
            f'<style>*{{margin:0;padding:0}}body{{width:440px;height:440px;background:#08080c;'
            f'display:flex;align-items:center;justify-content:center}}svg{{width:380px;height:380px}}</style>{svg}'
        )
        print(f"  wrote {out.name}  render at 440x440")
