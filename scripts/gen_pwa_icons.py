"""
Generate WeighBridge Setu PWA icons — WB wordmark, brand colours.

Fixes the "PWA icon not showing correctly" defect:
  - FULL-BLEED solid navy (no transparent rounded corners). A maskable icon
    must reach every edge; transparent corners let the OS mask show through.
  - Separate "any" and "maskable" variants. The maskable ones keep all content
    inside the inner ~80% safe zone so Android's circle/squircle crop never
    clips the wordmark or accent.
  - apple-touch-icon is fully opaque (iOS composites transparency on black).
  - New "-v3" filenames bust every HTTP / Cloudflare / service-worker cache.

Run:  py -3 scripts/gen_pwa_icons.py
"""
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = "frontend/public"

NAVY  = (15, 23, 42, 255)    # #0f172a
GREEN = (5, 150, 105, 255)   # #059669
WHITE = (255, 255, 255, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\Arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(size: int, out: str, *, content_scale: float, accent: bool = True) -> None:
    """Full-bleed navy square with centred white 'WB' + green underline.

    content_scale = cap height of the wordmark as a fraction of the canvas.
    Smaller scale => more padding (use for maskable safe zone).
    """
    img = Image.new("RGBA", (size, size), NAVY)   # opaque, edge-to-edge
    d = ImageDraw.Draw(img)
    cx, cy = size / 2.0, size / 2.0

    # Size the font so the rendered cap height ≈ content_scale * size.
    target_h = size * content_scale
    fs = max(8, int(target_h))
    font = load_font(fs)
    bbox = d.textbbox((0, 0), "WB", font=font)
    th = bbox[3] - bbox[1]
    if th > 0:
        fs = max(8, int(fs * target_h / th))
        font = load_font(fs)
        bbox = d.textbbox((0, 0), "WB", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Nudge the text up a little so the accent bar sits below it, group centred.
    accent_h = max(3, int(size * (0.05 if accent else 0)))
    gap = int(size * 0.05) if accent else 0
    group_h = th + gap + accent_h
    top = cy - group_h / 2.0

    # Draw WB (anchor at its visual top-left, correcting for bbox offset).
    d.text((cx - tw / 2.0 - bbox[0], top - bbox[1]), "WB", font=font, fill=WHITE)

    # Green underline pill, centred, below the wordmark.
    if accent:
        pill_w = tw * 0.92
        py0 = top + th + gap
        d.rounded_rectangle(
            [cx - pill_w / 2.0, py0, cx + pill_w / 2.0, py0 + accent_h],
            radius=accent_h / 2.0, fill=GREEN,
        )

    img.save(out, "PNG")
    print(f"  wrote {out}  ({size}x{size}, scale={content_scale})")


def main() -> None:
    print("Generating PWA icons (v3)…")
    # "any" purpose — tighter wordmark, looks like a proper app tile.
    make_icon(192, f"{OUT_DIR}/icon-192-v3.png", content_scale=0.46)
    make_icon(512, f"{OUT_DIR}/icon-512-v3.png", content_scale=0.46)
    make_icon(180, f"{OUT_DIR}/apple-touch-icon-v3.png", content_scale=0.46)
    make_icon(32,  f"{OUT_DIR}/favicon-32-v3.png", content_scale=0.55, accent=False)
    # "maskable" purpose — extra padding so nothing clips inside the 80% safe zone.
    make_icon(192, f"{OUT_DIR}/icon-maskable-192-v3.png", content_scale=0.34)
    make_icon(512, f"{OUT_DIR}/icon-maskable-512-v3.png", content_scale=0.34)
    print("Done.")


if __name__ == "__main__":
    main()
