"""Generate meme-style PnL cards for trade broadcasts."""

from PIL import Image, ImageDraw, ImageFont
import os
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent / "assets" / "templates"
OUTPUT_DIR = Path(__file__).parent.parent / "generated" / "cards"

def generate_pnl_card(pair: str, profit_pct: float, margin: float, reason: str = "") -> str:
    """
    Create a meme image showing trade result.
    Returns: path to generated PNG
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load template based on profit/loss
    template = "win.jpg" if profit_pct > 0 else "loss.jpg"
    template_path = TEMPLATE_DIR / template

    if not template_path.exists():
        # Create blank canvas if no template
        img = Image.new("RGB", (800, 600), color=(30, 30, 30))
    else:
        img = Image.open(template_path)

    draw = ImageDraw.Draw(img)

    # Try to load font, fallback to default
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 32)
    except:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Draw text
    color = (0, 255, 0) if profit_pct > 0 else (255, 0, 0)

    draw.text((50, 100), pair, fill=(255, 255, 255), font=font)
    draw.text((50, 200), f"{profit_pct:+.2f}%", fill=color, font=font)
    draw.text((50, 300), f"Margin: ${margin:.2f}", fill=(255, 255, 255), font=small_font)

    if reason:
        draw.text((50, 400), reason, fill=(200, 200, 200), font=small_font)

    output_path = OUTPUT_DIR / f"pnl_{pair.replace('/', '')}_{int(profit_pct*100)}.png"
    img.save(output_path)
    return str(output_path)
