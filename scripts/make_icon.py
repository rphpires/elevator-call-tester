"""Draw the app icon (elevator call buttons) from scratch. Needs Pillow; run once, output is committed."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "elevator_call_tester" / "assets"
SIZE = 256


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=44, fill=(28, 52, 84, 255))
    d.rounded_rectangle((70, 34, SIZE - 70, SIZE - 34), radius=58, fill=(214, 222, 232, 255))
    cx = SIZE // 2
    d.ellipse((cx - 38, 52, cx + 38, 128), fill=(28, 52, 84, 255))
    d.polygon([(cx, 66), (cx - 22, 106), (cx + 22, 106)], fill=(255, 196, 64, 255))
    d.ellipse((cx - 38, 128, cx + 38, 204), fill=(28, 52, 84, 255))
    d.polygon([(cx, 190), (cx - 22, 150), (cx + 22, 150)], fill=(214, 222, 232, 255))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.resize((64, 64), Image.LANCZOS).save(OUT / "icon.png")
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)
