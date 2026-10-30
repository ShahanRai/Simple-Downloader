import os
import math
from PIL import Image, ImageDraw, ImageFilter

def create_master_icon(size=512):
    # Create high-res canvas with transparent background
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = int(size * 0.06)
    radius = int(size * 0.22)
    box = [margin, margin, size - margin, size - margin]

    # 1. Base Squircle / Rounded Rectangle with Vertical Gradient
    # Gradient from #4f46e5 (Indigo) to #2563eb (Vibrant Blue) to #06b6d4 (Cyan)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(box, radius=radius, fill=255)

    gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(size):
        t = y / size
        # Smooth interpolation: top deep indigo (67, 56, 202) -> mid (79, 70, 229) -> bottom (37, 99, 235)
        if t < 0.5:
            k = t * 2.0
            r = int(67 * (1 - k) + 79 * k)
            g = int(56 * (1 - k) + 70 * k)
            b = int(202 * (1 - k) + 229 * k)
        else:
            k = (t - 0.5) * 2.0
            r = int(79 * (1 - k) + 37 * k)
            g = int(70 * (1 - k) + 99 * k)
            b = int(229 * (1 - k) + 235 * k)
        for x in range(size):
            gradient.putpixel((x, y), (r, g, b, 255))

    img.paste(gradient, (0, 0), mask)

    # 2. Inner Rim Glow & Top Specular Highlight
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rim_draw = ImageDraw.Draw(rim)
    rim_draw.rounded_rectangle(box, radius=radius, outline=(255, 255, 255, 60), width=int(size * 0.015))
    # Top highlight line
    rim_draw.rounded_rectangle([box[0] + 4, box[1] + 4, box[2] - 4, box[1] + int(size * 0.06)], radius=radius, fill=(255, 255, 255, 25))
    img = Image.alpha_composite(img, rim)

    # 3. Dynamic Multi-Stream Velocity Trails (3 horizontal acceleration bands in background)
    trails = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    trails_draw = ImageDraw.Draw(trails)
    center_x = size / 2
    
    # 3 stream stripes representing parallel connections
    stripe_w = int(size * 0.035)
    stripe_gap = int(size * 0.055)
    bar_y_top = int(size * 0.22)
    bar_y_bot = int(size * 0.44)
    for i in [-1, 0, 1]:
        sx = center_x + i * stripe_gap
        # Semi-transparent cyan glow
        trails_draw.rounded_rectangle(
            [sx - stripe_w // 2, bar_y_top + abs(i) * 20, sx + stripe_w // 2, bar_y_bot + abs(i) * 15],
            radius=stripe_w // 2,
            fill=(165, 180, 252, 120 if i != 0 else 180)
        )
    img = Image.alpha_composite(img, trails)

    # 4. Core Supersonic Download Glyph: High-Tech Aerodynamic Downward Dart & Bolt
    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glyph_draw = ImageDraw.Draw(glyph)

    # Points for a sleek faceted supersonic download bolt
    # Outer arrow shape
    arrow_pts = [
        (center_x, size * 0.77),                # Arrow tip at bottom
        (center_x - size * 0.26, size * 0.49),  # Left wing outer
        (center_x - size * 0.12, size * 0.49),  # Left inner notch
        (center_x - size * 0.12, size * 0.26),  # Left shaft top
        (center_x + size * 0.12, size * 0.26),  # Right shaft top
        (center_x + size * 0.12, size * 0.49),  # Right inner notch
        (center_x + size * 0.26, size * 0.49),  # Right wing outer
    ]
    # Draw drop shadow for glyph
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_pts = [(x, y + size * 0.02) for (x, y) in arrow_pts]
    shadow_draw.polygon(shadow_pts, fill=(15, 23, 42, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=size * 0.02))
    img = Image.alpha_composite(img, shadow)

    # Draw pure white solid glyph
    glyph_draw.polygon(arrow_pts, fill=(255, 255, 255, 255))

    # Dynamic lightning energy cut inside the arrow in electric cyan (#38bdf8 / #4edea3)
    # Energy carve: lightning diagonal cut that divides the arrow
    bolt_pts = [
        (center_x + size * 0.03, size * 0.28),
        (center_x - size * 0.08, size * 0.48),
        (center_x - size * 0.01, size * 0.48),
        (center_x - size * 0.05, size * 0.68),
        (center_x + size * 0.08, size * 0.46),
        (center_x + size * 0.01, size * 0.46),
    ]
    glyph_draw.polygon(bolt_pts, fill=(56, 189, 248, 255))

    # Base tray / speed bar beneath the arrow tip
    tray_w = size * 0.28
    tray_h = size * 0.045
    tray_y = size * 0.81
    glyph_draw.rounded_rectangle(
        [center_x - tray_w / 2, tray_y, center_x + tray_w / 2, tray_y + tray_h],
        radius=int(tray_h / 2),
        fill=(255, 255, 255, 255)
    )

    img = Image.alpha_composite(img, glyph)
    return img

def main():
    print("Generating brand new master icon...")
    master = create_master_icon(512)

    sizes = {
        "src-tauri/icons/icon.png": 512,
        "src-tauri/icons/128x128@2x.png": 256,
        "src-tauri/icons/128x128.png": 128,
        "src-tauri/icons/32x32.png": 32,
        "ui/icon.png": 128,
        "browser_extension/icons/icon128.png": 128,
        "browser_extension/icons/icon48.png": 48,
        "browser_extension/icons/icon32.png": 32,
        "browser_extension/icons/icon16.png": 16,
    }

    for path, sz in sizes.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        resized = master.resize((sz, sz), Image.Resampling.LANCZOS)
        resized.save(path, format="PNG")
        print(f"Saved: {path} ({sz}x{sz})")

    # Multi-resolution Windows .ico
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_imgs = [master.resize(s, Image.Resampling.LANCZOS) for s in ico_sizes]
    ico_path = "src-tauri/icons/icon.ico"
    ico_imgs[0].save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"Saved multi-resolution ICO: {ico_path}")

    # Also copy to installer folder if needed
    os.makedirs("installer", exist_ok=True)
    ico_imgs[0].save("installer/icon.ico", format="ICO", sizes=ico_sizes)
    print("Saved: installer/icon.ico")

if __name__ == "__main__":
    main()
