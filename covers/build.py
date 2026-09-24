#!/usr/bin/env python3
"""
Build the cover banners.

    python3 build.py            # writes the HTML
    ./render.sh                 # renders both to PNG

Drop the real Jolly artwork at covers/assets/jolly.png and it is composited
automatically. Without it the banners render complete, just without the
mascot. Nothing here draws a stand-in: Jolly is Meta's character and either
we use their asset or we use none.
"""

import base64
import pathlib

HERE = pathlib.Path(__file__).parent
JOLLY = HERE / "assets" / "jolly.png"

# Meta AI brand mark (simple-icons).
META_MARK = (
    "M10.73.032c-1.333 0-2.032 1.016-2.032 2.285 0 2.223 2.127 4.953 4.318 4.953 "
    "1.301 0 2-.953 2-2.254 0-2.254-2.095-4.984-4.286-4.984m8.413 2.984c-1.968 0-3.397 "
    "2.73-3.397 4.825 0 1.556.794 3.016 2.254 3.016 1.048 0 1.842-.572 2.826-2.19.286-.477 "
    "1.079-1.842 1.365-2.35.127-.222.19-.35.19-.35l-.032-.063c-.508-.984-1.492-2.888-3.206-2.888"
    "M7.111 5.048C4.222 5.048 1.27 7.873.508 11.365c-.317 1.397-.35 2.635-.35 3.714 0 3.365 "
    "1.777 5.492 4.476 5.492 2.762 0 4.73-2.286 6.508-5.302 0 0 .762-1.302 1.27-2.222.159-.286"
    ".318-.572.477-.858l-.032-.063c-.222-.413-.476-.921-.762-1.46-.508-.952-1.111-2.031-1.746-2.888"
    "C9.048 5.746 8.127 5.048 7.111 5.048"
)

# Kong, official mark. Wordmark glyphs recoloured white for a dark ground.
KONG_PATHS = [
    ("m14.5049 34.2245 1.0988-1.4039h8.1314l4.2383 5.3606-.7535 1.8188h-10.486l.2512-1.8188z", "#169fcc"),
    ("m16.9907 15.9454 3.9263-6.71493h4.5753l20.5076 23.58113-1.59 7.1878h-8.7936l.5516-2.0176z", "#14b59a"),
    ("m21.7568 7.95485 1.88-3.44169 5.6401-4.51316 9.6639 7.50029-1.2534 1.26628 1.6821 2.30533v2.4676l-4.8154 3.8962-8.0808-9.48085z", "#1bc263"),
    ("m6.82252 22.9514h2.5544l6.66088-5.5156 8.8272 10.1537-2.4897 3.698h-8.1483l-5.6261 7.0826-1.29337 1.6296h-7.30753v-8.6808z", "#16bdcc"),
    ("m77.8715 27.1807h6.1921v-9.4606h-6.1921zm.2169 3.7843c-1.7236 0-2.6189-.2793-3.3564-1.0464-1.1083-1.1093-1.5382-2.6513-1.5382-7.4308 0-4.7796.4299-6.3216 1.5382-7.4624.7099-.7395 1.6328-1.0188 3.3564-1.0188h5.7582c1.7236 0 2.6189.2793 3.3564 1.0188 1.1083 1.1408 1.5382 2.6514 1.5382 7.4624 0 4.8109-.4299 6.3215-1.5382 7.4308-.7375.771-1.6328 1.0464-3.3564 1.0464z", "#fff"),
    ("m102.748 19.3526v.1809 11.4276h4.709v-11.9822c0-2.4862-.276-3.3791-.986-4.0557-.647-.6452-1.574-.9363-3.021-.9363l-4.1416.0118-2.3743 2.1361v-2.1361h-1.5894-3.104v16.9584h4.7092v-13.2449h5.7901v1.6325z", "#fff"),
    ("m65.8271 9.33325h5.6084l-8.0537 10.16485 8.3929 11.4629h-5.9476l-6.3853-9.0043-1.5146-.0079v9.0122h-5.0483v-21.62775h5.0483v8.38285h1.5146z", "#fff"),
    ("m121.911 14.0029v2.136l-2.374-2.136-3.534-.0118c-1.692 0-2.686.2911-3.455 1.0267-1.017 1.0424-1.51 3.324-1.51 7.5017 0 4.1776.402 6.3648 1.384 7.3797.769.7356 1.684 1.0621 3.502 1.0621h5.975l.008 2.4271-8.294.0157.008.9953 2.142 2.3681h6.484c1.723 0 2.709-.3068 3.324-.952.769-.7985 1.077-1.2942 1.077-4.2091v-17.5996h-4.741zm.032 13.1584h-6.192v-9.4449h6.188v9.4449z", "#fff"),
]


def kong_svg(w: int) -> str:
    h = round(w * 40 / 127)
    paths = "".join(f'<path d="{d}" fill="{c}"/>' for d, c in KONG_PATHS)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 127 40" fill="none" aria-hidden="true">'
            f'<g clip-rule="evenodd" fill-rule="evenodd">{paths}</g></svg>')


def meta_svg(s: int) -> str:
    return (f'<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="#7b9cff" aria-hidden="true">'
            f'<path d="{META_MARK}"/></svg>')


def jolly_img(size: int) -> str:
    """Composite the real Jolly asset if it has been supplied, else nothing."""
    if not JOLLY.exists():
        return ""
    b64 = base64.b64encode(JOLLY.read_bytes()).decode()
    return (f'<img class="jolly" width="{size}" height="{size}" '
            f'src="data:image/png;base64,{b64}" alt="Muse avatar">')


TERMINAL = """
      <div class="term" style="{term_style}">
        <div class="term-bar" style="{bar_style}">
          <span class="dot" style="width:{dot}px;height:{dot}px;background:#ff5f56"></span>
          <span class="dot" style="width:{dot}px;height:{dot}px;background:#ffbd2e;margin-left:{dotgap}px"></span>
          <span class="dot" style="width:{dot}px;height:{dot}px;background:#27c93f;margin-left:{dotgap}px"></span>
          <span style="margin-left:{barpad}px">muse exec &mdash; on-call</span>
        </div>
        <div class="term-body" style="{body_style}">
          <div class="ln"><span class="mut">&gt;</span> investigate the checkout errors</div>
          <div class="ln"><span class="ok">&#10003;</span> <span class="tool">get-error-summary</span>   <span class="mut">PaymentProviderTimeout</span></div>
          <div class="ln"><span class="ok">&#10003;</span> <span class="tool">list-deployments</span>    <span class="mut">dep-482, 3 min before onset</span></div>
          <div class="ln"><span class="ok">&#10003;</span> <span class="tool">get-runbook</span>         <span class="mut">rb-204 &rarr; roll back first</span></div>
          <div class="ln"><span class="no">&#10007;</span> <span class="tool">rollback-deployment</span> <span class="no">403 denied by gateway</span></div>
          <div class="ln"><span class="mut">&nbsp;&nbsp;</span> <span class="amb">investigator identity &middot; 7 of 8 tools</span></div>
        </div>
      </div>
"""


def build(kind: str) -> str:
    big = kind == "hashnode"
    W, H = (1600, 840) if big else (1000, 420)
    s = 1.55 if big else 1.0          # type scale
    pad = "58px 64px" if big else "32px 44px"

    jolly = jolly_img(round(120 * s))
    jolly_block = (f'<div style="display:flex;align-items:center;gap:{round(18*s)}px">{jolly}</div>'
                   if jolly else "")

    term = TERMINAL.format(
        term_style=f"width:{round(438*s)}px",
        bar_style=f"padding:{round(9*s)}px {round(13*s)}px;font-size:{round(11*s)}px;gap:0",
        body_style=f"padding:{round(15*s)}px {round(16*s)}px;font-size:{round(11.5*s)}px;line-height:{round(21*s)}px",
        dot=round(8 * s), dotgap=round(6 * s), barpad=round(12 * s),
    )

    # Landscape dev.to banner puts the terminal beside the headline; the taller
    # Hashnode frame stacks brand row, headline, then terminal.
    if big:
        layout = f"""
    <div class="brands" style="gap:{round(16*s)}px">
      <div class="brand" style="gap:{round(10*s)}px">{meta_svg(round(30*s))}
        <span class="name" style="font-size:{round(16*s)}px">Muse&nbsp;Code</span></div>
      <span class="cross" style="font-size:{round(14*s)}px">&times;</span>
      <div class="brand">{kong_svg(round(92*s))}</div>
      <span class="spacer"></span>
      <span class="sev-tag" style="font-size:{round(11*s)}px;padding:{round(6*s)}px {round(12*s)}px">SEV2 &middot; CHECKOUT</span>
    </div>

    <div style="display:flex;align-items:center;gap:{round(46*s)}px;flex:1">
      <div style="flex:1">
        <h1 style="font-size:{round(86*s)}px;line-height:.95;letter-spacing:{-3.6*s:.1f}px">
          7 tools.<br><span class="dim">Or</span> <span class="hot">8</span>.</h1>
        <p class="sub" style="margin-top:{round(20*s)}px;font-size:{round(19*s)}px">
          Same agent. Same endpoint. <b>Different key.</b></p>
        {jolly_block}
      </div>
      {term}
    </div>

    <p class="sub" style="font-size:{round(14*s)}px;color:#636a77">
      Per-tool permissions for coding agents, at the gateway.</p>
"""
    else:
        layout = f"""
    <div class="brands" style="gap:14px">
      <div class="brand" style="gap:9px">{meta_svg(26)}
        <span class="name" style="font-size:15px">Muse&nbsp;Code</span></div>
      <span class="cross" style="font-size:13px">&times;</span>
      <div class="brand">{kong_svg(82)}</div>
      <span class="spacer"></span>
      <span class="sev-tag" style="font-size:10.5px;padding:5px 11px">SEV2 &middot; CHECKOUT</span>
    </div>

    <div style="display:flex;align-items:center;gap:36px;flex:1;padding:18px 0 4px">
      <div style="flex:1">
        <h1 style="font-size:66px;line-height:.95;letter-spacing:-3px">
          7 tools.<br><span class="dim">Or</span> <span class="hot">8</span>.</h1>
        <p class="sub" style="margin-top:13px;font-size:16px">
          Same agent. Same endpoint.<br><b>Different key.</b></p>
        {jolly_block}
      </div>
      {term}
    </div>
"""

    return f"""<!doctype html>
<meta charset="utf-8">
<link rel="stylesheet" href="cover.css">
<style>body {{ width: {W}px; height: {H}px; }}
  .sev {{ width: {5 if not big else 7}px; }}
  .frame {{ padding: {pad}; justify-content: space-between; }}
  .grid {{ background-size: {46 if not big else 64}px {46 if not big else 64}px; }}
</style>
<div class="wash"></div><div class="grid"></div><div class="sev"></div>
<div class="frame">
{layout}
</div>
"""


if __name__ == "__main__":
    for kind, name in (("devto", "cover-devto.html"), ("hashnode", "cover-hashnode.html")):
        (HERE / name).write_text(build(kind))
        print(f"  wrote {name}")
    print("  jolly:", "composited" if JOLLY.exists() else f"not supplied (drop it at {JOLLY})")
