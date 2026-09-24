#!/usr/bin/env python3
"""
Build the dev.to cover banner (1000x420).

dev.to's own recommendation is 1000x420, but the og:image it derives is
cropped at 840px, so everything load-bearing is kept inside x < 840.

Deliberately NOT a co-branded lockup: there is no "A x B" logo row, because
that reads as an official partnership. The only Kong artwork is the real mark
on the mascot's hard hat, and Muse Code is named in text. The character is
original work for this post.

    python3 banner.py            # all title variants
    python3 banner.py eyes       # one variant
"""

import json
import pathlib
import sys

import mascot

HERE = pathlib.Path(__file__).parent
SAFE = 840  # og:image crop boundary

VARIANTS = {
    "eyes": {
        "title": ['Give it <em>eyes</em>,', 'not <b>hands</b>.'],
        "sub": "Muse Code gets the whole incident.<br>The gateway decides what it can touch.",
    },
    "eighth": {
        "title": ['The <b>eighth</b>', 'tool.'],
        "sub": "Seven tools diagnose the outage.<br>The eighth one can change production.",
    },
    "readbreak": {
        "title": ['Read everything.', 'Break <b>nothing</b>.'],
        "sub": "Real production context for your coding agent,<br>without the deploy button.",
    },
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800;900&family=JetBrains+Mono:wght@500;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1000px; height:420px; overflow:hidden; background:#07070b;
         font-family:'Inter',system-ui,sans-serif; position:relative; }}

  /* 3am on-call: incident amber low-left, a cool safe glow upper-right */
  .wash {{ position:absolute; inset:0; background:
      radial-gradient(70% 110% at 10% 120%, rgba(255,124,42,.26), transparent 60%),
      radial-gradient(58% 92% at 88% -12%, rgba(47,227,212,.13), transparent 60%),
      linear-gradient(120deg,#120c14 0%,#08080d 44%,#06090b 100%); }}
  .grid {{ position:absolute; inset:0;
      background-image:
        linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),
        linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);
      background-size:44px 44px;
      mask-image:radial-gradient(74% 96% at 36% 52%,#000 38%,transparent 88%); }}
  .sev {{ position:absolute; left:0; top:0; bottom:0; width:5px;
      background:linear-gradient(180deg,#ff7c2a 0%,#ff4d4d 48%,#2fe3d4 100%); }}

  .frame {{ position:relative; height:100%; display:flex; align-items:center;
            gap:44px; padding:0 0 0 58px; }}

  .art {{ flex:0 0 auto; width:258px; height:258px; filter:drop-shadow(0 18px 40px rgba(0,0,0,.6)); }}
  .art svg {{ width:100%; height:100%; display:block; }}

  .copy {{ flex:0 1 auto; max-width:{copy_max}px; }}
  h1 {{ font-size:{fs}px; line-height:.98; font-weight:900; color:#fff;
        letter-spacing:-3px; }}
  h1 em {{ font-style:normal; color:#2fe3d4; }}
  h1 b {{ color:#ff7c2a; }}
  .sub {{ margin-top:16px; font-size:17px; line-height:1.45; font-weight:500;
          color:#98a0ad; letter-spacing:-.15px; }}

  .chip {{ display:inline-flex; align-items:center; gap:7px; margin-top:20px;
           font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700;
           letter-spacing:1.1px; color:#ffb020;
           border:1px solid rgba(255,176,32,.32); background:rgba(255,176,32,.07);
           padding:6px 11px; border-radius:5px; }}
  .dot {{ width:6px; height:6px; border-radius:50%; background:#ff7c2a; }}
</style>
<div class="wash"></div><div class="grid"></div><div class="sev"></div>
<div class="frame">
  <div class="art">{svg}</div>
  <div class="copy">
    <h1>{title}</h1>
    <p class="sub">{sub}</p>
    <span class="chip"><span class="dot"></span>PER-TOOL ACCESS AT THE GATEWAY</span>
  </div>
</div>
"""


def build(key: str) -> pathlib.Path:
    v = VARIANTS[key]
    cands = json.loads((HERE / "mascot-candidates.json").read_text())
    art = next(c for c in cands if c["key"].startswith("visor"))
    svg = mascot.inject(art["svg"])

    longest = max(len(l.replace("<em>", "").replace("</em>", "")
                      .replace("<b>", "").replace("</b>", "")) for l in v["title"])
    fs = 72 if longest <= 16 else 62 if longest <= 20 else 54

    html = PAGE.format(
        svg=svg,
        title="<br>".join(v["title"]),
        sub=v["sub"],
        fs=fs,
        copy_max=SAFE - 58 - 258 - 44,   # keep the copy inside the og crop
    )
    out = HERE / f"banner-{key}.html"
    out.write_text(html)
    return out


if __name__ == "__main__":
    keys = sys.argv[1:] or list(VARIANTS)
    for k in keys:
        print(f"  wrote {build(k).name}")
