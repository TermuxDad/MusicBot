import asyncio
import math
import os
import colorsys
import random
import tempfile
import uuid

import aiohttp

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)

from auro import config


# ============================================================
# FILE / OUTPUT SETTINGS
# ============================================================

FINAL_SIZE = (1920, 1080)
W, H = FINAL_SIZE

BASE_W = 1536
RATIO = FINAL_SIZE[0] / BASE_W


def S(value):
    if isinstance(value, (tuple, list)):
        return tuple(S(x) for x in value)
    return int(round(value * RATIO))


# ============================================================
# REFERENCE LAYOUT
# Based on the uploaded 1536x864 reference thumbnail.
# ============================================================

# LEFT COVER
CARD_BOX = S((108, 109, 732, 732))
CARD_RADIUS = S(24)

# RIGHT PANEL
RIGHT_X = S(858)
RIGHT_X_END = S(1441)

TITLE_Y = S(188)
SUBTITLE_Y = S(259)

TOP_ICON_Y = S(202)
TOP_ICON_R = S(28)

STAR_ICON_X = S(1331)
DOTS_ICON_X = S(1417)

SEEK_Y = S(328)
SEEK_THUMB_R = S(11)

TIME_Y = S(380)

PILL_CX = S(1144)
PILL_H = S(43)

CONTROLS_Y = S(522)

REWIND_X = S(945)
PLAY_CX = S(1120)
FORWARD_X = S(1319)

VOLUME_Y = S(664)

VOL_SPEAKER_LOW_X = S(878)
VOL_BAR_X0 = S(920)
VOL_BAR_X1 = S(1366)
VOL_SPEAKER_HIGH_X = S(1408)

BOTTOM_ICON_Y = S(764)
BOTTOM_ICON1_X = S(929)
BOTTOM_ICON3_X = S(1352)


# ============================================================
# COLORS
# ============================================================

WHITE = (255, 255, 255)
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (230, 230, 230)
MUTED = (205, 205, 205)

ACCENT_FALLBACK = (224, 176, 92)


# ============================================================
# FILE WRITE
# ============================================================

def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fw:
        fw.write(data)


# ============================================================
# THUMBNAIL CLASS
# ============================================================

class Thumbnail:

    def __init__(self):

        base = "auro/helpers"

        self.title_font_path = f"{base}/Poppins-ExtraBold.ttf"
        self.subtitle_font_path = f"{base}/Raleway-Bold.ttf"

        self.font_subtitle = ImageFont.truetype(
            self.subtitle_font_path,
            S(27),
        )

        self.font_time = ImageFont.truetype(
            self.subtitle_font_path,
            S(22),
        )

        self.font_pill = ImageFont.truetype(
            self.subtitle_font_path,
            S(20),
        )

        self._grain_cache_key = None
        self._grain_alpha_cache = None

    # ========================================================
    # DOWNLOAD
    # ========================================================

    async def save_thumb(self, output_path: str, url: str) -> str:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
        ) as session:

            async with session.get(
                url,
                allow_redirects=True,
            ) as resp:

                resp.raise_for_status()

                data = await resp.read()

        await asyncio.to_thread(
            _write_bytes,
            output_path,
            data,
        )

        return output_path

    # ========================================================
    # LOAD IMAGE
    # ========================================================

    def load_avatar(self, source):

        try:

            image = (
                source
                if isinstance(source, Image.Image)
                else Image.open(source)
            )

            return image.convert("RGB")

        except Exception:

            return None

    # ========================================================
    # FETCH AVATAR
    # ========================================================

    async def fetch_avatar(self, url, tmp_path):

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        try:

            timeout = aiohttp.ClientTimeout(total=20)

            async with aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            ) as session:

                async with session.get(
                    url,
                    allow_redirects=True,
                ) as resp:

                    resp.raise_for_status()

                    data = await resp.read()

                    content_type = resp.headers.get(
                        "Content-Type",
                        "",
                    )

                    if (
                        "image" not in content_type
                        and not data.startswith(
                            (
                                b"\xff\xd8",
                                b"\x89PNG",
                                b"GIF8",
                                b"RIFF",
                            )
                        )
                    ):
                        return None

                    await asyncio.to_thread(
                        _write_bytes,
                        tmp_path,
                        data,
                    )

            return await asyncio.to_thread(
                self.load_avatar,
                tmp_path,
            )

        except Exception as e:

            print(
                f"[Thumbnail] Avatar download failed: {e}"
            )

            return None

    # ========================================================
    # IMAGE FIT
    # ========================================================

    def fit_image(self, image, size):

        return ImageOps.fit(
            image,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    # ========================================================
    # ROUND CORNERS
    # ========================================================

    def add_round_corners(self, image, radius):

        image = image.convert("RGBA")

        w, h = image.size

        mask = Image.new(
            "L",
            (w, h),
            0,
        )

        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, w, h),
            radius=radius,
            fill=255,
        )

        result = Image.new(
            "RGBA",
            (w, h),
            (0, 0, 0, 0),
        )

        result.paste(
            image,
            (0, 0),
            mask,
        )

        return result

    # ========================================================
    # TITLE FONT
    # ========================================================

    def fit_title_font(
        self,
        draw,
        text,
        max_width,
        base_size,
        min_size,
    ):

        size = base_size

        while size >= min_size:

            font = ImageFont.truetype(
                self.title_font_path,
                size,
            )

            bbox = draw.textbbox(
                (0, 0),
                text,
                font=font,
            )

            if bbox[2] - bbox[0] <= max_width:
                return font

            size -= 2

        return ImageFont.truetype(
            self.title_font_path,
            min_size,
        )

    # ========================================================
    # TITLE + ELLIPSIS
    # ========================================================

    def fit_title_text_and_font(
        self,
        draw,
        text,
        max_width,
        base_size,
        min_size,
    ):

        text = text or "Unknown Title"

        font = self.fit_title_font(
            draw,
            text,
            max_width,
            base_size,
            min_size,
        )

        while True:

            bbox = draw.textbbox(
                (0, 0),
                text,
                font=font,
            )

            if bbox[2] - bbox[0] <= max_width:
                break

            if len(text) <= 8:
                break

            text = text[:-4].rstrip() + "..."

        return text, font

    # ========================================================
    # SIMPLE TRUNCATE
    # ========================================================

    def truncate(self, text, limit):

        text = str(text or "")

        if len(text) <= limit:
            return text

        return text[: limit - 3].rstrip() + "..."

    # ========================================================
    # TIME
    # ========================================================

    @staticmethod
    def _format_time(seconds):

        if seconds is None:
            return None

        try:
            seconds = int(seconds)
        except Exception:
            return None

        if seconds < 0:
            return None

        hours, remainder = divmod(
            seconds,
            3600,
        )

        minutes, secs = divmod(
            remainder,
            60,
        )

        if hours:

            return f"{hours}:{minutes:02d}:{secs:02d}"

        return f"{minutes}:{secs:02d}"

    # ========================================================
    # PARSE DURATION
    # ========================================================

    @staticmethod
    def _parse_duration(value):

        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):

            value = value.strip()

            if not value:
                return None

            if ":" in value:

                try:

                    parts = [
                        int(x)
                        for x in value.split(":")
                    ]

                except ValueError:

                    return None

                total = 0

                for part in parts:
                    total = total * 60 + part

                return float(total)

            try:
                return float(value)
            except ValueError:
                return None

        return None

    # ========================================================
    # FIRST ATTRIBUTE
    # ========================================================

    @staticmethod
    def _first_attr(
        obj,
        *names,
        default=None,
    ):

        for name in names:

            value = getattr(
                obj,
                name,
                None,
            )

            if value:
                return value

        return default

    # ========================================================
    # ACCENT COLOR
    # ========================================================

    def accent_from_cover(self, cover_img):

        try:

            small = (
                cover_img
                .convert("RGB")
                .resize((80, 80))
            )

            quant = small.quantize(
                colors=8,
                method=Image.Quantize.MEDIANCUT,
            )

            palette = quant.getpalette()

            colors = sorted(
                quant.getcolors() or [],
                key=lambda x: -x[0],
            )

            if colors:

                _, index = colors[0]

                r = palette[index * 3]
                g = palette[index * 3 + 1]
                b = palette[index * 3 + 2]

            else:

                r, g, b = ACCENT_FALLBACK

            h, s, v = colorsys.rgb_to_hsv(
                r / 255,
                g / 255,
                b / 255,
            )

            s = max(0.45, min(s, 0.90))
            v = max(0.45, min(v, 0.85))

            r, g, b = colorsys.hsv_to_rgb(
                h,
                s,
                v,
            )

            return (
                int(r * 255),
                int(g * 255),
                int(b * 255),
            )

        except Exception:

            return ACCENT_FALLBACK

    # ========================================================
    # BACKGROUND
    # ========================================================

    def build_background(self, cover_img):

        cover = cover_img.convert("RGB")

        # ----------------------------------------------------
        # Make the same cover fill the entire background.
        # ----------------------------------------------------

        bg = ImageOps.fit(
            cover,
            (W, H),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        # Slight zoom like reference.
        zoom = 1.08

        zw = int(W * zoom)
        zh = int(H * zoom)

        bg = bg.resize(
            (zw, zh),
            Image.Resampling.LANCZOS,
        )

        left = (zw - W) // 2
        top = (zh - H) // 2

        bg = bg.crop(
            (
                left,
                top,
                left + W,
                top + H,
            )
        )

        # ----------------------------------------------------
        # Strong but smooth blur.
        # ----------------------------------------------------

        bg = bg.filter(
            ImageFilter.GaussianBlur(
                S(38)
            )
        )

        # Slightly increase color.
        bg = ImageEnhance.Color(
            bg
        ).enhance(1.08)

        # Darken.
        bg = ImageEnhance.Brightness(
            bg
        ).enhance(0.58)

        # Slight contrast.
        bg = ImageEnhance.Contrast(
            bg
        ).enhance(1.08)

        bg = bg.convert("RGBA")

        # ----------------------------------------------------
        # Dark overlay.
        # ----------------------------------------------------

        overlay = Image.new(
            "RGBA",
            (W, H),
            (0, 0, 0, 95),
        )

        bg.alpha_composite(
            overlay
        )

        # ----------------------------------------------------
        # Soft center glow.
        # ----------------------------------------------------

        glow = Image.new(
            "RGBA",
            (W, H),
            (0, 0, 0, 0),
        )

        gd = ImageDraw.Draw(
            glow,
            "RGBA",
        )

        gd.ellipse(
            (
                S(150),
                S(-100),
                S(1400),
                S(1050),
            ),
            fill=(255, 255, 255, 20),
        )

        glow = glow.filter(
            ImageFilter.GaussianBlur(
                S(150)
            )
        )

        bg.alpha_composite(
            glow
        )

        # ----------------------------------------------------
        # Bottom / edge darkening.
        # ----------------------------------------------------

        vignette = Image.new(
            "L",
            (W, H),
            0,
        )

        vd = ImageDraw.Draw(
            vignette
        )

        vd.ellipse(
            (
                -S(150),
                -S(100),
                W + S(150),
                H + S(100),
            ),
            fill=255,
        )

        vignette = vignette.filter(
            ImageFilter.GaussianBlur(
                S(120)
            )
        )

        vignette = ImageOps.invert(
            vignette
        )

        vignette = vignette.point(
            lambda p: int(p * 0.42)
        )

        dark = Image.new(
            "RGBA",
            (W, H),
            (0, 0, 0, 0),
        )

        dark.putalpha(
            vignette
        )

        bg.alpha_composite(
            dark
        )

        return bg

    # ========================================================
    # COVER SHADOW
    # ========================================================

    def draw_card_shadow(self, canvas):

        x0, y0, x1, y1 = CARD_BOX

        shadow = Image.new(
            "RGBA",
            (W, H),
            (0, 0, 0, 0),
        )

        sd = ImageDraw.Draw(
            shadow
        )

        sd.rounded_rectangle(
            (
                x0 + S(8),
                y0 + S(20),
                x1 + S(8),
                y1 + S(20),
            ),
            radius=CARD_RADIUS,
            fill=(0, 0, 0, 185),
        )

        shadow = shadow.filter(
            ImageFilter.GaussianBlur(
                S(22)
            )
        )

        canvas.alpha_composite(
            shadow
        )

    # ========================================================
    # COVER CARD
    # ========================================================

    def draw_poster_card(
        self,
        canvas,
        cover_img,
        accent,
    ):

        self.draw_card_shadow(
            canvas
        )

        x0, y0, x1, y1 = CARD_BOX

        width = x1 - x0
        height = y1 - y0

        # ----------------------------------------------------
        # Main cover.
        # ----------------------------------------------------

        art = self.fit_image(
            cover_img.convert("RGB"),
            (width, height),
        ).convert("RGBA")

        # ----------------------------------------------------
        # Slight darkening at bottom.
        # ----------------------------------------------------

        shade = Image.new(
            "RGBA",
            (width, height),
            (0, 0, 0, 0),
        )

        sd = ImageDraw.Draw(
            shade,
            "RGBA",
        )

        sd.rectangle(
            (
                0,
                int(height * 0.88),
                width,
                height,
            ),
            fill=(0, 0, 0, 45),
        )

        shade = shade.filter(
            ImageFilter.GaussianBlur(
                S(10)
            )
        )

        art.alpha_composite(
            shade
        )

        # ----------------------------------------------------
        # Rounded corners.
        # ----------------------------------------------------

        art = self.add_round_corners(
            art,
            CARD_RADIUS,
        )

        # ----------------------------------------------------
        # Thin white border.
        # ----------------------------------------------------

        border = Image.new(
            "RGBA",
            (width, height),
            (0, 0, 0, 0),
        )

        bd = ImageDraw.Draw(
            border
        )

        bd.rounded_rectangle(
            (
                1,
                1,
                width - 2,
                height - 2,
            ),
            radius=CARD_RADIUS,
            outline=(255, 255, 255, 135),
            width=S(1),
        )

        art.alpha_composite(
            border
        )

        canvas.alpha_composite(
            art,
            (x0, y0),
        )

    # ========================================================
    # TOP CIRCLE BUTTON
    # ========================================================

    def draw_circle_button(
        self,
        canvas,
        cx,
        cy,
        radius,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        draw.ellipse(
            (
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
            ),
            fill=(45, 44, 43, 185),
            outline=(255, 255, 255, 225),
            width=S(2),
        )

    # ========================================================
    # STAR
    # ========================================================

    def draw_star_icon(
        self,
        canvas,
        cx,
        cy,
        r,
    ):

        self.draw_circle_button(
            canvas,
            cx,
            cy,
            r,
        )

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        points = []

        outer = r * 0.60
        inner = r * 0.26

        for i in range(10):

            angle = (
                -math.pi / 2
                + i * math.pi / 5
            )

            radius = (
                outer
                if i % 2 == 0
                else inner
            )

            points.append(
                (
                    cx + radius * math.cos(angle),
                    cy + radius * math.sin(angle),
                )
            )

        draw.polygon(
            points,
            fill=WHITE,
        )

    # ========================================================
    # THREE DOTS
    # ========================================================

    def draw_overflow_icon(
        self,
        canvas,
        cx,
        cy,
        r,
    ):

        self.draw_circle_button(
            canvas,
            cx,
            cy,
            r,
        )

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        dot_r = S(4)

        for offset in (
            -r * 0.35,
            0,
            r * 0.35,
        ):

            draw.ellipse(
                (
                    cx - dot_r,
                    cy + offset - dot_r,
                    cx + dot_r,
                    cy + offset + dot_r,
                ),
                fill=WHITE,
            )

    # ========================================================
    # SEEK BAR
    # ========================================================

    def draw_seekbar(
        self,
        canvas,
        fraction,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        fraction = max(
            0.0,
            min(1.0, fraction),
        )

        x0 = RIGHT_X
        x1 = RIGHT_X_END

        y = SEEK_Y

        thickness = S(10)

        # Track
        draw.rounded_rectangle(
            (
                x0,
                y - thickness / 2,
                x1,
                y + thickness / 2,
            ),
            radius=thickness // 2,
            fill=(255, 255, 255, 235),
        )

        # Thumb
        fx = x0 + (
            x1 - x0
        ) * fraction

        r = SEEK_THUMB_R

        draw.ellipse(
            (
                fx - r,
                y - r,
                fx + r,
                y + r,
            ),
            fill=WHITE,
        )

    # ========================================================
    # TIME ROW
    # ========================================================

    def draw_time_row(
        self,
        canvas,
        elapsed_text,
        remaining_text,
        bot_name,
        avatar_img,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = TIME_Y

        # Left time
        if elapsed_text:

            draw.text(
                (
                    RIGHT_X,
                    y,
                ),
                elapsed_text,
                font=self.font_time,
                fill=SUBTITLE_COLOR,
                anchor="lm",
            )

        # Right time
        if remaining_text:

            draw.text(
                (
                    RIGHT_X_END,
                    y,
                ),
                remaining_text,
                font=self.font_time,
                fill=SUBTITLE_COLOR,
                anchor="rm",
            )

        # ----------------------------------------------------
        # Bot pill
        # ----------------------------------------------------

        label = self.truncate(
            bot_name or "Team Auro",
            22,
        )

        pill_font = self.font_pill

        bbox = draw.textbbox(
            (0, 0),
            label,
            font=pill_font,
        )

        text_width = (
            bbox[2] - bbox[0]
        )

        avatar_size = 0

        if avatar_img is not None:
            avatar_size = PILL_H - S(12)

        gap = S(8) if avatar_img is not None else 0
        padding = S(18)

        pill_width = (
            text_width
            + padding * 2
            + avatar_size
            + gap
        )

        # Keep pill compact.
        max_width = S(260)

        if pill_width > max_width:

            label = self.truncate(
                label,
                17,
            )

            bbox = draw.textbbox(
                (0, 0),
                label,
                font=pill_font,
            )

            text_width = (
                bbox[2] - bbox[0]
            )

            pill_width = (
                text_width
                + padding * 2
                + avatar_size
                + gap
            )

        px0 = (
            PILL_CX
            - pill_width / 2
        )

        px1 = (
            PILL_CX
            + pill_width / 2
        )

        py0 = (
            y
            - PILL_H / 2
        )

        py1 = (
            y
            + PILL_H / 2
        )

        draw.rounded_rectangle(
            (
                px0,
                py0,
                px1,
                py1,
            ),
            radius=PILL_H // 2,
            fill=(30, 29, 28, 210),
            outline=(255, 255, 255, 220),
            width=S(1),
        )

        cursor_x = (
            px0 + padding
        )

        # Avatar
        if avatar_img is not None:

            avatar = self.fit_image(
                avatar_img.convert("RGB"),
                (
                    int(avatar_size),
                    int(avatar_size),
                ),
            )

            avatar = self.add_round_corners(
                avatar,
                int(avatar_size / 2),
            )

            canvas.alpha_composite(
                avatar,
                (
                    int(cursor_x),
                    int(
                        y
                        - avatar_size / 2
                    ),
                ),
            )

            cursor_x += (
                avatar_size
                + gap
            )

        draw.text(
            (
                cursor_x,
                y,
            ),
            label,
            font=pill_font,
            fill=WHITE,
            anchor="lm",
        )

    # ========================================================
    # TRANSPORT CONTROLS
    # ========================================================

    def draw_transport_controls(
        self,
        canvas,
        playing=True,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = CONTROLS_Y

        # ----------------------------------------------------
        # PLAY / PAUSE
        # ----------------------------------------------------

        if playing:

            bar_width = S(19)
            bar_height = S(80)
            gap = S(24)

            left_x = (
                PLAY_CX
                - gap / 2
                - bar_width
            )

            right_x = (
                PLAY_CX
                + gap / 2
            )

            draw.rounded_rectangle(
                (
                    left_x,
                    y - bar_height / 2,
                    left_x + bar_width,
                    y + bar_height / 2,
                ),
                radius=S(7),
                fill=WHITE,
            )

            draw.rounded_rectangle(
                (
                    right_x,
                    y - bar_height / 2,
                    right_x + bar_width,
                    y + bar_height / 2,
                ),
                radius=S(7),
                fill=WHITE,
            )

        else:

            size = S(48)

            draw.polygon(
                [
                    (
                        PLAY_CX - size * 0.45,
                        y - size * 0.65,
                    ),
                    (
                        PLAY_CX - size * 0.45,
                        y + size * 0.65,
                    ),
                    (
                        PLAY_CX + size * 0.65,
                        y,
                    ),
                ],
                fill=WHITE,
            )

        # ----------------------------------------------------
        # PREVIOUS / NEXT
        # ----------------------------------------------------

        tri_w = S(35)
        tri_h = S(55)
        gap = S(7)

        # Previous
        for i in (0, 1):

            cx = (
                REWIND_X
                - (i - 0.5)
                * (tri_w + gap)
            )

            draw.polygon(
                [
                    (
                        cx + tri_w / 2,
                        y - tri_h / 2,
                    ),
                    (
                        cx + tri_w / 2,
                        y + tri_h / 2,
                    ),
                    (
                        cx - tri_w / 2,
                        y,
                    ),
                ],
                fill=WHITE,
            )

        # Next
        for i in (0, 1):

            cx = (
                FORWARD_X
                + (i - 0.5)
                * (tri_w + gap)
            )

            draw.polygon(
                [
                    (
                        cx - tri_w / 2,
                        y - tri_h / 2,
                    ),
                    (
                        cx - tri_w / 2,
                        y + tri_h / 2,
                    ),
                    (
                        cx + tri_w / 2,
                        y,
                    ),
                ],
                fill=WHITE,
            )

    # ========================================================
    # SPEAKER ICON
    # ========================================================

    def draw_speaker(
        self,
        draw,
        cx,
        cy,
        loud=False,
    ):

        body_w = S(10)
        body_h = S(22)
        cone = S(18)

        draw.rectangle(
            (
                cx - body_w,
                cy - body_h / 2,
                cx,
                cy + body_h / 2,
            ),
            fill=WHITE,
        )

        draw.polygon(
            [
                (
                    cx,
                    cy - body_h / 2,
                ),
                (
                    cx,
                    cy + body_h / 2,
                ),
                (
                    cx + cone,
                    cy + body_h / 2 + S(8),
                ),
                (
                    cx + cone,
                    cy - body_h / 2 - S(8),
                ),
            ],
            fill=WHITE,
        )

        if loud:

            for radius in (
                S(14),
                S(22),
            ):

                draw.arc(
                    (
                        cx + cone - radius,
                        cy - radius,
                        cx + cone + radius,
                        cy + radius,
                    ),
                    start=-42,
                    end=42,
                    fill=WHITE,
                    width=S(2),
                )

    # ========================================================
    # VOLUME
    # ========================================================

    def draw_volume_row(
        self,
        canvas,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = VOLUME_Y

        thickness = S(10)

        # Main volume line
        draw.rounded_rectangle(
            (
                VOL_BAR_X0,
                y - thickness / 2,
                VOL_BAR_X1,
                y + thickness / 2,
            ),
            radius=thickness // 2,
            fill=WHITE,
        )

        # Low speaker
        self.draw_speaker(
            draw,
            VOL_SPEAKER_LOW_X,
            y,
            loud=False,
        )

        # High speaker
        self.draw_speaker(
            draw,
            VOL_SPEAKER_HIGH_X,
            y,
            loud=True,
        )

    # ========================================================
    # BOTTOM ICONS
    # ========================================================

    def draw_bottom_icons(
        self,
        canvas,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = BOTTOM_ICON_Y

        # ----------------------------------------------------
        # COMMENT / CAPTION
        # ----------------------------------------------------

        cx = BOTTOM_ICON1_X

        width = S(40)
        height = S(32)

        draw.rounded_rectangle(
            (
                cx - width / 2,
                y - height / 2,
                cx + width / 2,
                y + height / 2,
            ),
            radius=S(8),
            outline=MUTED,
            width=S(2),
        )

        draw.polygon(
            [
                (
                    cx - S(6),
                    y + height / 2,
                ),
                (
                    cx + S(2),
                    y + height / 2,
                ),
                (
                    cx - S(1),
                    y + height / 2 + S(9),
                ),
            ],
            fill=MUTED,
        )

        qfont = ImageFont.truetype(
            self.subtitle_font_path,
            S(14),
        )

        draw.text(
            (
                cx,
                y - S(2),
            ),
            '"',
            font=qfont,
            fill=MUTED,
            anchor="mm",
        )

        # ----------------------------------------------------
        # QUEUE / LIST
        # ----------------------------------------------------

        cx = BOTTOM_ICON3_X

        line_length = S(40)

        start_x = (
            cx
            - line_length / 2
        )

        for dy in (
            -S(12),
            0,
            S(12),
        ):

            dot_r = S(2)

            draw.ellipse(
                (
                    start_x - dot_r,
                    y + dy - dot_r,
                    start_x + dot_r,
                    y + dy + dot_r,
                ),
                fill=MUTED,
            )

            draw.line(
                (
                    start_x + S(10),
                    y + dy,
                    start_x + line_length,
                    y + dy,
                ),
                fill=MUTED,
                width=S(2),
            )

    # ========================================================
    # NOW PLAYING PANEL
    # ========================================================

    def draw_now_playing_panel(
        self,
        canvas,
        title,
        channel_name,
        bot_name,
        avatar_img=None,
        duration=None,
        elapsed=3,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title_max_width = (
            STAR_ICON_X
            - TOP_ICON_R
            - RIGHT_X
            - S(25)
        )

        title = self.truncate(
            title or "Unknown Title",
            38,
        )

        title, title_font = (
            self.fit_title_text_and_font(
                draw,
                title,
                title_max_width,
                S(43),
                S(24),
            )
        )

        draw.text(
            (
                RIGHT_X,
                TITLE_Y,
            ),
            title,
            font=title_font,
            fill=TITLE_COLOR,
        )

        # ----------------------------------------------------
        # ARTIST / CHANNEL
        # ----------------------------------------------------

        artist = self.truncate(
            channel_name or "Unknown Artist",
            35,
        )

        draw.text(
            (
                RIGHT_X,
                SUBTITLE_Y,
            ),
            artist,
            font=self.font_subtitle,
            fill=SUBTITLE_COLOR,
        )

        # ----------------------------------------------------
        # TOP BUTTONS
        # ----------------------------------------------------

        self.draw_star_icon(
            canvas,
            STAR_ICON_X,
            TOP_ICON_Y,
            TOP_ICON_R,
        )

        self.draw_overflow_icon(
            canvas,
            DOTS_ICON_X,
            TOP_ICON_Y,
            TOP_ICON_R,
        )

        # ----------------------------------------------------
        # DURATION
        # ----------------------------------------------------

        duration = self._parse_duration(
            duration
        )

        elapsed = (
            self._parse_duration(
                elapsed
            )
            or 0
        )

        fraction = 0.01
        elapsed_text = self._format_time(
            elapsed
        )

        remaining_text = None

        if duration and duration > 0:

            elapsed = min(
                elapsed,
                duration,
            )

            fraction = (
                elapsed / duration
            )

            remaining = max(
                0,
                duration - elapsed,
            )

            remaining_text = (
                "-"
                + self._format_time(
                    remaining
                )
            )

        # ----------------------------------------------------
        # SEEK
        # ----------------------------------------------------

        self.draw_seekbar(
            canvas,
            fraction,
        )

        # ----------------------------------------------------
        # TIME
        # ----------------------------------------------------

        self.draw_time_row(
            canvas,
            elapsed_text,
            remaining_text,
            bot_name,
            avatar_img,
        )

        # ----------------------------------------------------
        # CONTROLS
        # ----------------------------------------------------

        self.draw_transport_controls(
            canvas,
            playing=True,
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        self.draw_volume_row(
            canvas
        )

        # ----------------------------------------------------
        # BOTTOM
        # ----------------------------------------------------

        self.draw_bottom_icons(
            canvas
        )

    # ========================================================
    # GRAIN
    # ========================================================

    def apply_grain(
        self,
        canvas,
        opacity=5,
    ):

        width, height = canvas.size

        key = (
            width,
            height,
            opacity,
        )

        if self._grain_cache_key != key:

            small_w = max(
                1,
                width // 4,
            )

            small_h = max(
                1,
                height // 4,
            )

            rng = random.Random(
                77
            )

            noise_bytes = rng.randbytes(
                small_w * small_h
            )

            noise = Image.frombytes(
                "L",
                (
                    small_w,
                    small_h,
                ),
                noise_bytes,
            )

            noise = noise.resize(
                (
                    width,
                    height,
                ),
                Image.Resampling.BILINEAR,
            )

            self._grain_alpha_cache = (
                noise.point(
                    lambda p:
                    int(
                        p
                        * opacity
                        / 255
                    )
                )
            )

            self._grain_cache_key = key

        grain = Image.new(
            "RGBA",
            (
                width,
                height,
            ),
            (128, 128, 128, 0),
        )

        grain.putalpha(
            self._grain_alpha_cache
        )

        canvas.alpha_composite(
            grain
        )

    # ========================================================
    # COMPOSE
    # ========================================================

    def compose(
        self,
        cover_img,
        title,
        channel_name,
        bot_name,
        avatar_img=None,
        duration=None,
        elapsed=3,
        **kwargs,
    ):

        cover = cover_img.convert(
            "RGB"
        )

        # ----------------------------------------------------
        # BACKGROUND
        # ----------------------------------------------------

        canvas = self.build_background(
            cover
        )

        # ----------------------------------------------------
        # COVER
        # ----------------------------------------------------

        accent = self.accent_from_cover(
            cover
        )

        self.draw_poster_card(
            canvas,
            cover,
            accent,
        )

        # ----------------------------------------------------
        # RIGHT PANEL
        # ----------------------------------------------------

        self.draw_now_playing_panel(
            canvas,
            title,
            channel_name,
            bot_name,
            avatar_img=avatar_img,
            duration=duration,
            elapsed=elapsed,
        )

        # ----------------------------------------------------
        # VERY LIGHT GRAIN
        # ----------------------------------------------------

        self.apply_grain(
            canvas,
            opacity=5,
        )

        result = canvas.convert(
            "RGB"
        )

        canvas.close()
        cover.close()

        return result

    # ========================================================
    # GENERATE
    # ========================================================

    async def generate(
        self,
        media,
        output_path=None,
        user_avatar=None,
    ):

        # ----------------------------------------------------
        # COVER URL
        # ----------------------------------------------------

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
                "generate(): No thumbnail/cover URL found."
            )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title = self._first_attr(
            media,
            "title",
            "name",
            default="Unknown Title",
        )

        # ----------------------------------------------------
        # ARTIST / CHANNEL
        # ----------------------------------------------------

        channel_name = self._first_attr(
            media,
            "channel",
            "channel_name",
            "uploader",
            "artist",
            "user",
            default="Unknown Artist",
        )

        # ----------------------------------------------------
        # BOT NAME
        # ----------------------------------------------------

        bot_name = self._first_attr(
            config,
            "BOT_NAME",
            "NAME",
            "APP_NAME",
            default="Team Auro",
        )

        # ----------------------------------------------------
        # DURATION
        # ----------------------------------------------------

        duration = self._first_attr(
            media,
            "duration",
            "duration_seconds",
            "length",
            "track_duration",
            "seconds",
            default=None,
        )

        duration = self._parse_duration(
            duration
        )

        # ----------------------------------------------------
        # AVATAR
        # ----------------------------------------------------

        avatar_source = (
            user_avatar
            or self._first_attr(
                media,
                "user_photo",
                "user_photo_url",
                "user_avatar",
                "requester_photo",
                "played_by_photo",
                "user_pic",
                "user_dp",
                default=None,
            )
        )

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------

        if not output_path:

            media_id = self._first_attr(
                media,
                "id",
                default=uuid.uuid4().hex,
            )

            output_path = os.path.join(
                tempfile.gettempdir(),
                f"thumb_{media_id}.jpg",
            )

        tmp_cover = (
            f"{output_path}.cover_tmp.jpg"
        )

        tmp_avatar = (
            f"{output_path}.avatar_tmp.jpg"
        )

        cover_img = None
        avatar_img = None
        final_img = None

        try:

            # ------------------------------------------------
            # DOWNLOAD COVER
            # ------------------------------------------------

            cover_task = asyncio.create_task(
                self.save_thumb(
                    tmp_cover,
                    cover_url,
                )
            )

            # ------------------------------------------------
            # AVATAR
            # ------------------------------------------------

            if isinstance(
                avatar_source,
                Image.Image,
            ):

                avatar_img = (
                    avatar_source.convert(
                        "RGB"
                    )
                )

            elif (
                asyncio.isfuture(
                    avatar_source
                )
                or isinstance(
                    avatar_source,
                    asyncio.Task,
                )
            ):

                resolved = await avatar_source

                if isinstance(
                    resolved,
                    Image.Image,
                ):

                    avatar_img = (
                        resolved.convert(
                            "RGB"
                        )
                    )

                elif (
                    isinstance(
                        resolved,
                        str,
                    )
                    and os.path.isfile(
                        resolved
                    )
                ):

                    avatar_img = await asyncio.to_thread(
                        self.load_avatar,
                        resolved,
                    )

                elif (
                    isinstance(
                        resolved,
                        str,
                    )
                    and resolved.startswith(
                        (
                            "http://",
                            "https://",
                        )
                    )
                ):

                    avatar_img = await self.fetch_avatar(
                        resolved,
                        tmp_avatar,
                    )

            elif (
                isinstance(
                    avatar_source,
                    str,
                )
                and os.path.isfile(
                    avatar_source
                )
            ):

                avatar_img = await asyncio.to_thread(
                    self.load_avatar,
                    avatar_source,
                )

            elif (
                isinstance(
                    avatar_source,
                    str,
                )
                and avatar_source.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ):

                avatar_img = await self.fetch_avatar(
                    avatar_source,
                    tmp_avatar,
                )

            # ------------------------------------------------
            # WAIT COVER
            # ------------------------------------------------

            await cover_task

            cover_img = await asyncio.to_thread(
                self.load_avatar,
                tmp_cover,
            )

            if cover_img is None:

                raise ValueError(
                    f"Could not load thumbnail: {cover_url}"
                )

            # ------------------------------------------------
            # CPU IMAGE GENERATION OFF EVENT LOOP
            # ------------------------------------------------

            final_img = await asyncio.to_thread(
                self.compose,
                cover_img,
                title,
                channel_name,
                bot_name,
                avatar_img=avatar_img,
                duration=duration,
                elapsed=3,
            )

            # ------------------------------------------------
            # SAVE JPG
            # ------------------------------------------------

            await asyncio.to_thread(
                final_img.save,
                output_path,
                "JPEG",
                quality=94,
                optimize=True,
                progressive=True,
            )

        finally:

            for image in (
                avatar_img,
                cover_img,
                final_img,
            ):

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass

            for temp in (
                tmp_cover,
                tmp_avatar,
            ):

                try:

                    if os.path.exists(
                        temp
                    ):
                        os.remove(temp)

                except Exception:
                    pass

        return output_path
