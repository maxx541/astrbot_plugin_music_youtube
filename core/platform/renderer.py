"""Lyrics/subtitle rendering as image"""

import io
import re

from PIL import Image, ImageDraw, ImageFont

from .config import PluginConfig


class MusicRenderer:
    """Render lyrics/subtitles as image"""
    
    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.font_path = config.font_path

    def draw_lyrics(
        self,
        lyrics: str,
        image_width=1000,
        font_size=30,
        line_spacing=20,
        top_color=(255, 250, 240),  # Warm white
        bottom_color=(235, 255, 247),  # Light blue
        text_color=(70, 70, 70),  # Dark gray
    ) -> bytes:
        """
        Render lyrics/subtitles as image with gradient background.
        
        Returns:
            JPEG bytes
        """
        # Clean lyrics text
        lines = self._clean_lyrics(lyrics)
        
        # Load font
        font = ImageFont.truetype(str(self.font_path), font_size)

        # Calculate total height
        dummy_img = Image.new("RGB", (image_width, 1))
        draw = ImageDraw.Draw(dummy_img)
        line_heights = [
            draw.textbbox(
                (0, 0), 
                line if line.strip() else "　", 
                font=font
            )[3]
            for line in lines
        ]
        total_height = int(
            sum(line_heights) + line_spacing * (len(lines) - 1) + 100
        )

        # Create gradient background
        img = Image.new("RGB", (image_width, total_height))
        for y in range(total_height):
            ratio = y / total_height
            r = int(
                top_color[0] * (1 - ratio) 
                + bottom_color[0] * ratio
            )
            g = int(
                top_color[1] * (1 - ratio) 
                + bottom_color[1] * ratio
            )
            b = int(
                top_color[2] * (1 - ratio) 
                + bottom_color[2] * ratio
            )
            for x in range(image_width):
                img.putpixel((x, y), (r, g, b))

        draw = ImageDraw.Draw(img)

        # Draw lyrics text (centered)
        y = 50
        for line, line_height in zip(lines, line_heights):
            text = line if line.strip() else "　"  # Full-width space placeholder
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            draw.text(
                ((image_width - text_width) / 2, y),
                text,
                font=font,
                fill=text_color
            )
            y += line_height + line_spacing

        # Output to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        img_bytes.seek(0)
        return img_bytes.getvalue()

    def _clean_lyrics(self, lyrics: str) -> list[str]:
        """
        Clean lyrics/subtitle text.
        
        Removes:
        - LRC time stamps [mm:ss.xx] or [mm:ss]
        - Other time formats HH:MM:SS,mmm
        
        Preserves:
        - Empty lines
        - Content
        """
        lines = lyrics.splitlines()
        cleaned_lines = []
        
        for line in lines:
            # Remove LRC time stamps [mm:ss.xx] or [mm:ss]
            cleaned = re.sub(
                r'\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]', 
                '', 
                line
            )
            
            # Remove other time stamp formats
            cleaned = re.sub(
                r'^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*', 
                '', 
                cleaned
            )
            
            # Strip but preserve empty lines
            cleaned = cleaned.strip()
            cleaned_lines.append(
                cleaned if cleaned != "" else ""
            )
        
        return cleaned_lines
