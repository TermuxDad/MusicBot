
import asyncio
import math
import os
import re
import tempfile
import uuid

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from auro import config


FINAL_SIZE = (1280, 720)
W, H = FINAL_SIZE


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fw:
        fw.write(data)


class Thumbnail:
    """Fast, self-contained now-playing thumbnail generator.

    Keeps the original project API:
        thumb = Thumbnail()
        path = await thumb.generate(media)

    The visual layout follows the supplied reference thumbnail:
    blurred artwork background, large centred artwork, neon glow
    frame/ring, NOW PLAYING badge, bot badge, and bottom player bar.
    """

    def __init__(self):
        base = "auro/helpers"
        self.font_bold_path = f"{base}/Poppins-ExtraBold.ttf"
        self.font_regular_path = f"{base}/Raleway-Bold.ttf"

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _first_attr(obj, *names, default=None):
        for name in names:
            try:
                value = getattr(obj, name, None)
            except Exception:
                value = None
            if value not in (None, ""):
                return value
        return default

    @staticmethod
    def _parse_duration(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if ":" in text:
                try:
                    parts = [int(x) for x in text.split(":")]
                except ValueError:
                    return None
                total = 0
                for part in parts:
                    total = total * 60 + part
                return float(total)
            try:
                return float(text)
            except ValueError:
                return None
        return None

    @staticmethod
    def _duration_text(value):
        seconds = Thumbnail._parse_duration(value)
        if seconds is None:
            return "Unknown"
        seconds = max(0, int(seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _safe_text(text, limit=45):
        text = str(text or "").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 3)].rstrip() + "..."

    @staticmethod
    def fit_image(image, size):
        return ImageOps.fit(
            image.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    @staticmethod
    def _load_font(paths, size):
        for path in paths:
            try:
                return ImageFont.truetype(path, int(size))
            except Exception:
                pass
        return ImageFont.load_default()

    async def save_thumb(self, output_path: str, url: str) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.read()
        await asyncio.to_thread(_write_bytes, output_path, data)
        return output_path

    @staticmethod
    def load_image(source):
        try:
            if isinstance(source, Image.Image):
                return source.convert("RGB")
            return Image.open(source).convert("RGB")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Colour / neon helpers
    # ------------------------------------------------------------------

    @staticmethod
    def dominant_color(img):
        small = img.convert("RGB").resize((80, 80), Image.Resampling.BILINEAR)
        colors = small.getcolors(80 * 80)
        if not colors:
            return (30, 144, 255)

        # Prefer saturated, useful colours instead of black/grey pixels.
        best = (30, 144, 255)
        best_score = -1.0

        for count, rgb in colors:
            r, g, b = rgb
            mx = max(r, g, b)
            mn = min(r, g, b)
            sat = (mx - mn) / max(1, mx)
            lum = (mx + mn) / 510.0

            # Avoid almost-black and almost-white colours.
            score = count * (0.25 + sat) * (0.35 + (1.0 - abs(lum - 0.5)))
            if score > best_score:
                best_score = score
                best = rgb

        return tuple(int(x) for x in best)

    @staticmethod
    def build_palette(base):
        rainbow = [
            (0x1E, 0x90, 0xFF),  # blue
            (0x06, 0xB6, 0xD4),  # cyan
            (0x14, 0xB8, 0xA6),  # teal
            (0x22, 0xC5, 0x5E),  # green
            (0xF5, 0x9E, 0x0B),  # amber
            (0xF9, 0x73, 0x16),  # orange
            (0xF4, 0x3F, 0x5E),  # rose
            (0xEC, 0x48, 0x99),  # pink
            (0xA8, 0x55, 0xF7),  # purple
            (0xE2, 0xE8, 0xF0),  # white
        ]
        br, bg, bb = base

        def dist(c):
            return math.sqrt(
                (c[0] - br) ** 2 * 0.299
                + (c[1] - bg) ** 2 * 0.587
                + (c[2] - bb) ** 2 * 0.114
            )

        idx = min(range(len(rainbow)), key=lambda i: dist(rainbow[i]))
        return rainbow[idx:] + rainbow[:idx]

    @staticmethod
    def make_neon_border(size, bbox, dominant, radius=28, stroke=5):
        neon = [
            (0x1E, 0x90, 0xFF),
            (0x06, 0xB6, 0xD4),
            (0x14, 0xB8, 0xA6),
            (0x22, 0xC5, 0x5E),
            (0xF5, 0x9E, 0x0B),
            (0xF9, 0x73, 0x16),
            (0xF4, 0x3F, 0x5E),
            (0xEC, 0x48, 0x99),
            (0xA8, 0x55, 0xF7),
            (0xE2, 0xE8, 0xF0),
        ]

        dr, dg, db = dominant

        def dist(c):
            return math.sqrt(
                (c[0] - dr) ** 2 * 0.299
                + (c[1] - dg) ** 2 * 0.587
                + (c[2] - db) ** 2 * 0.114
            )

        ordered = sorted(neon, key=dist)
        primary = ordered[0]
        secondary = ordered[1]

        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x0, y0, x1, y1 = bbox

        # Soft halo.
        for i in range(10, 0, -1):
            t = i / 10.0
            expand = int((t ** 0.5) * 34)
            alpha = int(8 + (1.0 - t) ** 1.2 * 110)
            col = primary if i % 2 == 0 else secondary
            draw.rounded_rectangle(
                (
                    max(0, x0 - expand),
                    max(0, y0 - expand),
                    min(size[0], x1 + expand),
                    min(size[1], y1 + expand),
                ),
                radius=max(8, radius - expand // 7),
                outline=(*col, alpha),
                width=max(1, stroke + int(t * 8)),
            )

        # Bright edge.
        draw.rounded_rectangle(
            bbox,
            radius=radius,
            outline=(
                min(255, primary[0] + 90),
                min(255, primary[1] + 90),
                min(255, primary[2] + 90),
                255,
            ),
            width=stroke,
        )

        # White highlight.
        draw.rounded_rectangle(
            bbox,
            radius=radius,
            outline=(255, 255, 255, 90),
            width=max(1, stroke // 3),
        )
        return layer

    # ------------------------------------------------------------------
    # Reference-style drawing
    # ------------------------------------------------------------------

    def _draw_progress(self, draw, x0, y0, x1, height, fraction, palette):
        fraction = max(0.0, min(1.0, float(fraction)))
        thumb_x = int(x0 + (x1 - x0) * fraction)
        base = palette[0]
        accent = palette[7]

        draw.rounded_rectangle(
            (x0, y0, x1, y0 + height),
            radius=max(1, height // 2),
            fill=(45, 45, 70, 180),
        )

        # Glow.
        for glow in range(6, 0, -1):
            pad = glow * 2
            alpha = 12 + (6 - glow) * 14
            draw.rounded_rectangle(
                (
                    x0,
                    y0 - pad // 2,
                    max(x0, thumb_x),
                    y0 + height + pad // 2,
                ),
                radius=max(1, height // 2 + pad // 2),
                fill=(
                    min(255, base[0] + 55),
                    min(255, base[1] + 55),
                    min(255, base[2] + 55),
                    alpha,
                ),
            )

        draw.rounded_rectangle(
            (x0, y0, max(x0, thumb_x), y0 + height),
            radius=max(1, height // 2),
            fill=(
                min(255, base[0] + 70),
                min(255, base[1] + 70),
                min(255, base[2] + 70),
                240,
            ),
        )

        draw.rounded_rectangle(
            (x0, y0, max(x0, thumb_x), y0 + max(1, height // 3)),
            radius=max(1, height // 2),
            fill=(
                min(255, accent[0] + 80),
                min(255, accent[1] + 80),
                min(255, accent[2] + 80),
                125,
            ),
        )

        tr = 9
        cy = y0 + height // 2
        for glow in range(5, 0, -1):
            rr = tr + glow * 3
            alpha = 18 + (5 - glow) * 22
            draw.ellipse(
                (thumb_x - rr, cy - rr, thumb_x + rr, cy + rr),
                fill=(
                    min(255, accent[0] + 70),
                    min(255, accent[1] + 70),
                    min(255, accent[2] + 70),
                    alpha,
                ),
            )

        draw.ellipse(
            (thumb_x - tr, cy - tr, thumb_x + tr, cy + tr),
            fill=(255, 255, 255, 250),
        )
        draw.ellipse(
            (thumb_x - tr + 3, cy - tr + 3, thumb_x + tr - 3, cy + tr - 3),
            fill=(
                min(255, accent[0] + 90),
                min(255, accent[1] + 90),
                min(255, accent[2] + 90),
                210,
            ),
        )

    def compose(
        self,
        cover_img,
        title,
        channel_name,
        bot_name,
        avatar_img=None,
        duration=None,
        elapsed=0,
        **_ignored,
    ):
        del avatar_img  # The reference design does not require an avatar.

        cover = cover_img.convert("RGB")
        cover = ImageEnhance.Sharpness(cover).enhance(1.25)
        cover = ImageEnhance.Color(cover).enhance(1.18)

        dominant = self.dominant_color(cover)
        palette = self.build_palette(dominant)

        canvas = Image.new("RGBA", (W, H), (10, 6, 22, 255))

        # --------------------------------------------------------------
        # Background
        # --------------------------------------------------------------
        bg = ImageOps.fit(
            cover,
            (W, H),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.45),
        )
        bg = bg.filter(ImageFilter.GaussianBlur(25))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        bg = ImageEnhance.Color(bg).enhance(1.15)
        canvas.alpha_composite(bg.convert("RGBA"))

        # Dark translucent overlay.
        canvas.alpha_composite(
            Image.new("RGBA", (W, H), (5, 3, 18, 105))
        )

        # --------------------------------------------------------------
        # Bottom player bar
        # --------------------------------------------------------------
        BOTTOM_H = 185
        CZ_H = H - BOTTOM_H

        fade = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fade)
        for row in range(150):
            alpha = int((row / 149.0) ** 1.55 * 225)
            fd.line((0, row, W, row), fill=(10, 6, 22, alpha))
        canvas.alpha_composite(fade, (0, CZ_H - 65))

        r, g, b = dominant
        bar = Image.new(
            "RGBA",
            (W, BOTTOM_H + 20),
            (max(0, r - 150), max(0, g - 150), max(0, b - 145), 238),
        )
        bar = Image.alpha_composite(
            bar, Image.new("RGBA", bar.size, (0, 0, 0, 90))
        )
        canvas.alpha_composite(bar, (0, CZ_H - 16))

        # --------------------------------------------------------------
        # Main cover art
        # --------------------------------------------------------------
        CV_W, CV_H = 390, 320
        CV_LEFT = (W - CV_W) // 2
        CV_TOP = (CZ_H - CV_H) // 2 + 30

        cover_sq = cover.resize((CV_W, CV_H), Image.Resampling.LANCZOS)
        cover_sq = ImageEnhance.Sharpness(cover_sq).enhance(1.35)
        cover_sq = ImageEnhance.Contrast(cover_sq).enhance(1.08)

        mask = Image.new("L", (CV_W, CV_H), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, CV_W - 1, CV_H - 1),
            radius=22,
            fill=255,
        )
        cover_sq.putalpha(mask)

        shadow = Image.new("RGBA", (CV_W + 80, CV_H + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (24, 24, CV_W + 56, CV_H + 56),
            radius=30,
            fill=(r // 2, g // 2, b // 2, 175),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas.alpha_composite(shadow, (CV_LEFT - 40, CV_TOP - 40))
        canvas.alpha_composite(cover_sq, (CV_LEFT, CV_TOP))

        # Neon ring around artwork.
        ring = self.make_neon_border(
            (W, H),
            (CV_LEFT - 10, CV_TOP - 10, CV_LEFT + CV_W + 10, CV_TOP + CV_H + 10),
            dominant,
            radius=28,
            stroke=5,
        )
        canvas.alpha_composite(ring)

        # Outer neon frame.
        outer = self.make_neon_border(
            (W, H),
            (6, 6, W - 6, H - 6),
            dominant,
            radius=30,
            stroke=5,
        )
        canvas.alpha_composite(outer)

        draw = ImageDraw.Draw(canvas, "RGBA")

        # --------------------------------------------------------------
        # Top badges
        # --------------------------------------------------------------
        font_badge = self._load_font(
            [self.font_regular_path, self.font_bold_path], 18
        )
        font_bold = self._load_font(
            [self.font_bold_path, self.font_regular_path], 32
        )
        font_small = self._load_font(
            [self.font_regular_path, self.font_bold_path], 24
        )
        font_dur = self._load_font(
            [self.font_regular_path, self.font_bold_path], 22
        )

        p0 = palette[0]

        # NOW PLAYING
        BW, BH = 210, 42
        badge = Image.new("RGBA", (BW, BH), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.rounded_rectangle(
            (0, 0, BW - 1, BH - 1),
            radius=BH // 2,
            fill=(max(0, p0[0] - 80), max(0, p0[1] - 80), max(0, p0[2] - 80), 210),
            outline=(
                min(255, p0[0] + 100),
                min(255, p0[1] + 100),
                min(255, p0[2] + 100),
                220,
            ),
            width=2,
        )
        canvas.alpha_composite(badge, (28, 26))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.text(
            (48, 34),
            "NOW PLAYING",
            fill=(230, 235, 255, 245),
            font=font_badge,
        )

        # Bot name badge.
        bot_label = self._safe_text(bot_name or "Music Bot", 18)
        try:
            text_width = draw.textlength(bot_label, font=font_badge)
        except Exception:
            text_width = len(bot_label) * 11

        RBW = int(text_width) + 36
        RBH = BH
        RB_X = W - RBW - 28
        RB_Y = 26

        draw.rounded_rectangle(
            (RB_X, RB_Y, RB_X + RBW, RB_Y + RBH),
            radius=RBH // 2,
            fill=(max(0, p0[0] - 80), max(0, p0[1] - 80), max(0, p0[2] - 80), 210),
            outline=(
                min(255, p0[0] + 100),
                min(255, p0[1] + 100),
                min(255, p0[2] + 100),
                220,
            ),
            width=2,
        )
        draw.text(
            (RB_X + 18, RB_Y + 10),
            bot_label,
            fill=(230, 235, 255, 245),
            font=font_badge,
        )

        # --------------------------------------------------------------
        # Bottom information
        # --------------------------------------------------------------
        BAR_Y = CZ_H - 16
        IS = 118
        ICON_X = 52
        ICON_Y = BAR_Y + (BOTTOM_H - IS) // 2

        icon_img = cover.resize((IS, IS), Image.Resampling.LANCZOS).convert("RGBA")
        icon_mask = Image.new("L", (IS, IS), 0)
        ImageDraw.Draw(icon_mask).rounded_rectangle(
            (0, 0, IS - 1, IS - 1), radius=16, fill=255
        )
        icon_img.putalpha(icon_mask)
        canvas.alpha_composite(icon_img, (ICON_X, ICON_Y))

        draw = ImageDraw.Draw(canvas, "RGBA")
        TEXT_X = ICON_X + IS + 22
        LINE1_Y = BAR_Y + 16
        LINE2_Y = BAR_Y + 54

        title_text = self._safe_text(title or "Unknown Title", 40)
        channel_text = self._safe_text(channel_name or "Unknown Channel", 32)
        bot_text = self._safe_text(bot_name or "Music Bot", 20)

        draw.text(
            (TEXT_X, LINE1_Y),
            title_text,
            fill=(255, 255, 255, 250),
            font=font_bold,
        )
        draw.text(
            (TEXT_X, LINE2_Y),
            f"Played by: {bot_text}  ·  {channel_text}",
            fill=(175, 180, 215, 205),
            font=font_small,
        )

        # Progress.
        PROG_X0 = TEXT_X
        PROG_X1 = W - 32
        BAR_H_PX = 8
        PROG_Y = BAR_Y + BOTTOM_H - 52

        duration_seconds = self._parse_duration(duration)
        if duration_seconds and duration_seconds > 0:
            frac = max(
                0.0,
                min(1.0, float(elapsed or 0) / duration_seconds),
            )
        else:
            frac = 0.65

        self._draw_progress(
            draw,
            PROG_X0,
            PROG_Y,
            PROG_X1,
            BAR_H_PX,
            frac,
            palette,
        )

        TIME_Y = PROG_Y + BAR_H_PX + 8
        duration_text = self._duration_text(duration)

        draw.text(
            (PROG_X0, TIME_Y),
            self._duration_text(elapsed or 0),
            fill=(195, 200, 230, 210),
            font=font_dur,
        )

        # Right-aligned duration.
        try:
            dw = draw.textlength(duration_text, font=font_dur)
        except Exception:
            dw = 70
        draw.text(
            (PROG_X1 - dw, TIME_Y),
            duration_text,
            fill=(195, 200, 230, 210),
            font=font_dur,
        )

        # Slight final sharpening.
        final = canvas.convert("RGB")
        final = ImageEnhance.Sharpness(final).enhance(1.05)
        return final

    # ------------------------------------------------------------------
    # Original bot-facing API
    # ------------------------------------------------------------------

    async def generate(self, media, output_path=None, user_avatar=None) -> str:
        cover_url = self._first_attr(
            media,
            "thumb",
            "thumbnail",
            "cover",
            "cover_url",
            "image",
            "photo",
            "photo_url",
            "art",
            "artwork",
        )
        if not cover_url:
            raise ValueError(
                "generate(): no thumbnail URL found on media object"
            )

        title = self._first_attr(
            media, "title", "name", default="Unknown Title"
        )
        channel_name = self._first_attr(
            media,
            "channel",
            "channel_name",
            "uploader",
            "artist",
            "user",
            default="Unknown Channel",
        )
        bot_name = self._first_attr(
            config, "BOT_NAME", "NAME", "APP_NAME", default="Music Bot"
        )
        duration = self._first_attr(
            media,
            "duration",
            "duration_seconds",
            "length",
            "track_duration",
            "seconds",
            default=None,
        )

        elapsed = self._first_attr(
            media,
            "elapsed",
            "position",
            "played_seconds",
            default=0,
        )

        if not output_path:
            media_id = self._first_attr(
                media, "id", "videoid", "video_id", default=uuid.uuid4().hex
            )
            output_path = os.path.join(
                tempfile.gettempdir(), f"thumb_{media_id}.jpg"
            )

        tmp_cover = f"{output_path}.cover_tmp"

        try:
            await self.save_thumb(tmp_cover, str(cover_url))
            cover_img = await asyncio.to_thread(self.load_image, tmp_cover)

            if cover_img is None:
                raise ValueError(
                    f"Failed to decode thumbnail image: {cover_url}"
                )

            final_img = await asyncio.to_thread(
                self.compose,
                cover_img,
                title,
                channel_name,
                bot_name,
                avatar_img=None,
                duration=duration,
                elapsed=elapsed,
            )

            # JPEG keeps Telegram upload size reasonable while retaining
            # the crisp reference-style artwork.
            await asyncio.to_thread(
                final_img.save,
                output_path,
                "JPEG",
                quality=95,
                optimize=True,
            )

            cover_img.close()
            final_img.close()
            return output_path

        finally:
            try:
                if os.path.exists(tmp_cover):
                    os.remove(tmp_cover)
            except Exception:
                pass
