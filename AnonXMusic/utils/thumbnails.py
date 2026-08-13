import os
import re
import math
import asyncio
import tempfile

import aiofiles
import aiohttp
from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)
from unidecode import unidecode
from ytSearch import VideosSearch

from AnonXMusic import app
from config import YOUTUBE_IMG_URL


# ============================================================
# SETTINGS
# ============================================================

FINAL_SIZE = (1920, 1080)
W, H = FINAL_SIZE

BASE_W = 1280
RATIO = W / BASE_W


def S(value):
    if isinstance(value, (tuple, list)):
        return tuple(S(x) for x in value)
    return int(round(value * RATIO))


# ============================================================
# LAYOUT - SECOND CODE STYLE
# ============================================================

CARD_BOX = S((90, 90, 610, 610))
CARD_RADIUS = S(24)

RIGHT_X = S(716)
RIGHT_X_END = S(1200)

TITLE_Y = S(149)
SUBTITLE_Y = S(211)

TOP_ICON_Y = S(168)
TOP_ICON_R = S(24)

STAR_ICON_X = S(1109)
DOTS_ICON_X = S(1181)

SEEK_Y = S(274)
SEEK_THUMB_R = S(9)

TIME_Y = S(314)

PILL_CX = S(952)
PILL_H = S(34)

CONTROLS_Y = S(434)
REWIND_X = S(791)
PLAY_CX = S(952)
FORWARD_X = S(1116)

VOLUME_Y = S(553)

VOL_SPEAKER_LOW_X = S(731)
VOL_BAR_X0 = S(766)
VOL_BAR_X1 = S(1138)
VOL_SPEAKER_HIGH_X = S(1172)

BOTTOM_ICON_Y = S(635)
BOTTOM_ICON1_X = S(774)
BOTTOM_ICON3_X = S(1131)


# ============================================================
# COLORS
# ============================================================

WHITE = (255, 255, 255)
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (222, 222, 222)
MUTED = (185, 185, 185)

ACCENT_FALLBACK = (224, 176, 92)


# ============================================================
# FILE HELPERS
# ============================================================

async def download_file(url, path):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        )
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:

            if response.status != 200:
                raise ValueError(
                    f"Thumbnail download failed: HTTP {response.status}"
                )

            data = await response.read()

    def write_file():
        with open(path, "wb") as f:
            f.write(data)

    await asyncio.to_thread(write_file)


def load_image(path):
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


# ============================================================
# THUMBNAIL CLASS
# ============================================================

class Thumbnail:

    def __init__(self):
        base = "AnonXMusic/assets"

        self.title_font_path = f"{base}/Poppins-ExtraBold.ttf"
        self.subtitle_font_path = f"{base}/Raleway-Bold.ttf"

        # Fallback fonts
        if not os.path.exists(self.title_font_path):
            self.title_font_path = f"{base}/font2.ttf"

        if not os.path.exists(self.subtitle_font_path):
            self.subtitle_font_path = f"{base}/font.ttf"

        try:
            self.font_subtitle = ImageFont.truetype(
                self.subtitle_font_path,
                S(24),
            )
            self.font_time = ImageFont.truetype(
                self.subtitle_font_path,
                S(20),
            )
            self.font_pill = ImageFont.truetype(
                self.subtitle_font_path,
                S(17),
            )
        except Exception:
            self.font_subtitle = ImageFont.load_default()
            self.font_time = ImageFont.load_default()
            self.font_pill = ImageFont.load_default()


    # ========================================================
    # BASIC HELPERS
    # ========================================================

    def fit_image(self, image, size):
        return ImageOps.fit(
            image,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )


    def round_image(self, image, radius):
        image = image.convert("RGBA")

        w, h = image.size

        mask = Image.new("L", (w, h), 0)

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


    def truncate(self, text, limit):
        text = str(text or "")

        if len(text) <= limit:
            return text

        return text[:limit - 3] + "..."


    def fit_title(self, draw, text, max_width):
        text = self.truncate(text, 50)

        size = S(46)

        while size >= S(24):

            try:
                font = ImageFont.truetype(
                    self.title_font_path,
                    size,
                )
            except Exception:
                font = ImageFont.load_default()

            box = draw.textbbox(
                (0, 0),
                text,
                font=font,
            )

            if box[2] - box[0] <= max_width:
                return text, font

            size -= S(2)

        return self.truncate(text, 30), font


    # ========================================================
    # DURATION
    # ========================================================

    @staticmethod
    def parse_duration(value):

        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):

            value = value.strip()

            if ":" in value:

                try:
                    parts = [
                        int(x)
                        for x in value.split(":")
                    ]
                except Exception:
                    return None

                seconds = 0

                for part in parts:
                    seconds = seconds * 60 + part

                return float(seconds)

            try:
                return float(value)

            except Exception:
                return None

        return None


    @staticmethod
    def format_time(seconds):

        if seconds is None:
            return None

        seconds = max(0, int(seconds))

        minutes, secs = divmod(seconds, 60)

        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            return f"{hours}:{minutes:02d}:{secs:02d}"

        return f"{minutes}:{secs:02d}"


    # ========================================================
    # ACCENT COLOR
    # ========================================================

    def get_accent(self, image):

        try:
            small = image.convert("RGB").resize(
                (60, 60),
                Image.Resampling.BILINEAR,
            )

            colors = small.getcolors(60 * 60)

            if colors:

                colors.sort(
                    key=lambda x: x[0],
                    reverse=True,
                )

                color = colors[0][1]

                r, g, b = color

                # Make it brighter and more visible
                maximum = max(r, g, b)
                minimum = min(r, g, b)

                if maximum - minimum < 35:
                    return ACCENT_FALLBACK

                factor = 1.25

                r = min(255, int(r * factor))
                g = min(255, int(g * factor))
                b = min(255, int(b * factor))

                return (r, g, b)

        except Exception:
            pass

        return ACCENT_FALLBACK


    # ========================================================
    # BACKGROUND
    # ========================================================

    def build_background(self, cover):

        cover = cover.convert("RGB")

        zoom_size = (
            int(W * 1.25),
            int(H * 1.25),
        )

        zoomed = ImageOps.fit(
            cover,
            zoom_size,
            method=Image.Resampling.LANCZOS,
        )

        left = (zoom_size[0] - W) // 2
        top = (zoom_size[1] - H) // 2

        background = zoomed.crop(
            (
                left,
                top,
                left + W,
                top + H,
            )
        )

        zoomed.close()

        # Strong blur
        small = background.resize(
            (
                max(1, W // 5),
                max(1, H // 5),
            ),
            Image.Resampling.BILINEAR,
        )

        background.close()

        background = small.resize(
            FINAL_SIZE,
            Image.Resampling.BILINEAR,
        )

        small.close()

        background = background.filter(
            ImageFilter.GaussianBlur(S(20))
        )

        background = ImageEnhance.Color(
            background
        ).enhance(1.12)

        background = ImageEnhance.Contrast(
            background
        ).enhance(1.05)

        background = ImageEnhance.Brightness(
            background
        ).enhance(0.72)

        background = background.convert("RGBA")

        # Dark overlay
        dark = Image.new(
            "RGBA",
            FINAL_SIZE,
            (0, 0, 0, 120),
        )

        background.alpha_composite(dark)

        # Extra dark area on right
        right_dark = Image.new(
            "RGBA",
            FINAL_SIZE,
            (5, 5, 8, 0),
        )

        rd = ImageDraw.Draw(
            right_dark,
            "RGBA",
        )

        rd.rectangle(
            (
                S(600),
                0,
                W,
                H,
            ),
            fill=(5, 5, 8, 100),
        )

        right_dark = right_dark.filter(
            ImageFilter.GaussianBlur(S(40))
        )

        background.alpha_composite(right_dark)

        return background


    # ========================================================
    # CARD GLOW
    # ========================================================

    def draw_card_glow(self, canvas, accent):

        x0, y0, x1, y1 = CARD_BOX

        glow = Image.new(
            "RGBA",
            FINAL_SIZE,
            (0, 0, 0, 0),
        )

        gd = ImageDraw.Draw(
            glow,
            "RGBA",
        )

        gd.rounded_rectangle(
            (
                x0 - S(20),
                y0 - S(20),
                x1 + S(20),
                y1 + S(20),
            ),
            radius=CARD_RADIUS + S(20),
            outline=(
                accent[0],
                accent[1],
                accent[2],
                130,
            ),
            width=S(20),
        )

        glow = glow.filter(
            ImageFilter.GaussianBlur(S(35))
        )

        # Keep glow only around left card
        mask = Image.new(
            "L",
            FINAL_SIZE,
            0,
        )

        ImageDraw.Draw(mask).rectangle(
            (
                0,
                0,
                RIGHT_X - S(40),
                H,
            ),
            fill=255,
        )

        alpha = glow.getchannel("A")

        glow.putalpha(
            Image.composite(
                alpha,
                Image.new("L", FINAL_SIZE, 0),
                mask,
            )
        )

        canvas.alpha_composite(glow)


    # ========================================================
    # POSTER CARD
    # ========================================================

    def draw_poster_card(
        self,
        canvas,
        cover,
        accent,
    ):

        self.draw_card_glow(
            canvas,
            accent,
        )

        x0, y0, x1, y1 = CARD_BOX

        width = x1 - x0
        height = y1 - y0

        # Shadow
        shadow = Image.new(
            "RGBA",
            FINAL_SIZE,
            (0, 0, 0, 0),
        )

        ImageDraw.Draw(
            shadow
        ).rounded_rectangle(
            (
                x0 + S(8),
                y0 + S(20),
                x1 + S(8),
                y1 + S(20),
            ),
            radius=CARD_RADIUS,
            fill=(0, 0, 0, 170),
        )

        shadow = shadow.filter(
            ImageFilter.GaussianBlur(S(28))
        )

        canvas.alpha_composite(
            shadow
        )

        # Cover
        art = self.fit_image(
            cover,
            (width, height),
        ).convert("RGBA")

        art = ImageEnhance.Sharpness(
            art
        ).enhance(1.25)

        art = ImageEnhance.Color(
            art
        ).enhance(1.10)

        # Slight dark edge
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
            (0, 0, width, S(80)),
            fill=(0, 0, 0, 45),
        )

        sd.rectangle(
            (
                0,
                height - S(80),
                width,
                height,
            ),
            fill=(0, 0, 0, 45),
        )

        art.alpha_composite(
            shade
        )

        art = self.round_image(
            art,
            CARD_RADIUS,
        )

        # Border
        border = Image.new(
            "RGBA",
            (width, height),
            (0, 0, 0, 0),
        )

        ImageDraw.Draw(
            border
        ).rounded_rectangle(
            (
                0,
                0,
                width - 1,
                height - 1,
            ),
            radius=CARD_RADIUS,
            outline=(
                255,
                255,
                255,
                100,
            ),
            width=S(2),
        )

        art.alpha_composite(
            border
        )

        canvas.alpha_composite(
            art,
            (x0, y0),
        )


    # ========================================================
    # TOP ICONS
    # ========================================================

    def icon_circle(
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
            fill=(40, 38, 38, 170),
            outline=(255, 255, 255, 150),
            width=S(1),
        )


    def draw_star(
        self,
        canvas,
        cx,
        cy,
        radius,
    ):

        self.icon_circle(
            canvas,
            cx,
            cy,
            radius,
        )

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        points = []

        outer = radius * 0.60
        inner = radius * 0.25

        for i in range(10):

            angle = (
                -math.pi / 2
                + i * math.pi / 5
            )

            r = (
                outer
                if i % 2 == 0
                else inner
            )

            points.append(
                (
                    cx + r * math.cos(angle),
                    cy + r * math.sin(angle),
                )
            )

        draw.polygon(
            points,
            fill=WHITE,
        )


    def draw_overflow(
        self,
        canvas,
        cx,
        cy,
        radius,
    ):

        self.icon_circle(
            canvas,
            cx,
            cy,
            radius,
        )

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        dot = S(3)

        for dy in (
            -radius * 0.36,
            0,
            radius * 0.36,
        ):

            draw.ellipse(
                (
                    cx - dot,
                    cy + dy - dot,
                    cx + dot,
                    cy + dy + dot,
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

        thickness = S(9)

        fx = (
            x0
            + (x1 - x0) * fraction
        )

        draw.rounded_rectangle(
            (
                x0,
                y - thickness / 2,
                x1,
                y + thickness / 2,
            ),
            radius=thickness // 2,
            fill=(255, 255, 255, 145),
        )

        draw.ellipse(
            (
                fx - SEEK_THUMB_R,
                y - SEEK_THUMB_R,
                fx + SEEK_THUMB_R,
                y + SEEK_THUMB_R,
            ),
            fill=(255, 255, 255, 245),
        )


    # ========================================================
    # BOT NAME PILL
    # ========================================================

    def draw_time_row(
        self,
        canvas,
        elapsed,
        remaining,
        bot_name,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        if elapsed:
            draw.text(
                (
                    RIGHT_X,
                    TIME_Y,
                ),
                elapsed,
                font=self.font_time,
                fill=SUBTITLE_COLOR,
                anchor="lm",
            )

        if remaining:
            draw.text(
                (
                    RIGHT_X_END,
                    TIME_Y,
                ),
                remaining,
                font=self.font_time,
                fill=SUBTITLE_COLOR,
                anchor="rm",
            )

        label = self.truncate(
            bot_name or "Music Bot",
            22,
        )

        font = self.font_pill

        box = draw.textbbox(
            (0, 0),
            label,
            font=font,
        )

        text_width = (
            box[2] - box[0]
        )

        padding = S(16)

        pill_width = (
            text_width
            + padding * 2
        )

        max_width = S(260)

        if pill_width > max_width:

            label = self.truncate(
                label,
                16,
            )

            box = draw.textbbox(
                (0, 0),
                label,
                font=font,
            )

            text_width = (
                box[2] - box[0]
            )

            pill_width = (
                text_width
                + padding * 2
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
            TIME_Y
            - PILL_H / 2
        )

        py1 = (
            TIME_Y
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
            fill=(35, 33, 32, 180),
            outline=(255, 255, 255, 65),
            width=S(1),
        )

        draw.text(
            (
                PILL_CX,
                TIME_Y,
            ),
            label,
            font=font,
            fill=WHITE,
            anchor="mm",
        )


    # ========================================================
    # PLAY / SKIP CONTROLS
    # ========================================================

    def draw_controls(
        self,
        canvas,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = CONTROLS_Y

        # Pause
        bar_w = S(17)
        bar_h = S(65)
        gap = S(19)

        for dx in (
            -gap / 2 - bar_w / 2,
            gap / 2 + bar_w / 2,
        ):

            draw.rounded_rectangle(
                (
                    PLAY_CX + dx - bar_w / 2,
                    y - bar_h / 2,
                    PLAY_CX + dx + bar_w / 2,
                    y + bar_h / 2,
                ),
                radius=bar_w // 3,
                fill=WHITE,
            )

        # Skip buttons
        tri_w = S(28)
        tri_h = S(42)
        gap = S(6)

        for cx, direction in (
            (REWIND_X, -1),
            (FORWARD_X, 1),
        ):

            for i in (0, 1):

                offset = (
                    i - 0.5
                ) * (
                    tri_w + gap
                ) * direction

                if direction > 0:

                    points = [
                        (
                            cx + offset - tri_w / 2,
                            y - tri_h / 2,
                        ),
                        (
                            cx + offset - tri_w / 2,
                            y + tri_h / 2,
                        ),
                        (
                            cx + offset + tri_w / 2,
                            y,
                        ),
                    ]

                else:

                    points = [
                        (
                            cx + offset + tri_w / 2,
                            y - tri_h / 2,
                        ),
                        (
                            cx + offset + tri_w / 2,
                            y + tri_h / 2,
                        ),
                        (
                            cx + offset - tri_w / 2,
                            y,
                        ),
                    ]

                draw.polygon(
                    points,
                    fill=WHITE,
                )


    # ========================================================
    # VOLUME
    # ========================================================

    def draw_volume(
        self,
        canvas,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        y = VOLUME_Y

        thickness = S(9)

        draw.rounded_rectangle(
            (
                VOL_BAR_X0,
                y - thickness / 2,
                VOL_BAR_X1,
                y + thickness / 2,
            ),
            radius=thickness // 2,
            fill=(255, 255, 255, 230),
        )

        # Left speaker
        cx = VOL_SPEAKER_LOW_X

        body_w = S(9)
        body_h = S(12)
        cone = S(11)

        draw.rectangle(
            (
                cx - body_w,
                y - body_h / 2,
                cx,
                y + body_h / 2,
            ),
            fill=WHITE,
        )

        draw.polygon(
            [
                (
                    cx,
                    y - body_h / 2,
                ),
                (
                    cx,
                    y + body_h / 2,
                ),
                (
                    cx + cone,
                    y + body_h / 2 + cone * 0.6,
                ),
                (
                    cx + cone,
                    y - body_h / 2 - cone * 0.6,
                ),
            ],
            fill=WHITE,
        )

        # Right speaker
        cx = VOL_SPEAKER_HIGH_X

        draw.rectangle(
            (
                cx - body_w,
                y - body_h / 2,
                cx,
                y + body_h / 2,
            ),
            fill=WHITE,
        )

        draw.polygon(
            [
                (
                    cx,
                    y - body_h / 2,
                ),
                (
                    cx,
                    y + body_h / 2,
                ),
                (
                    cx + cone,
                    y + body_h / 2 + cone * 0.6,
                ),
                (
                    cx + cone,
                    y - body_h / 2 - cone * 0.6,
                ),
            ],
            fill=WHITE,
        )

        for radius in (
            S(10),
            S(16),
        ):

            draw.arc(
                (
                    cx + cone - radius,
                    y - radius,
                    cx + cone + radius,
                    y + radius,
                ),
                -40,
                40,
                fill=WHITE,
                width=S(2),
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

        # Quote icon
        cx = BOTTOM_ICON1_X

        width = S(34)
        height = S(24)

        draw.rounded_rectangle(
            (
                cx - width / 2,
                y - height / 2,
                cx + width / 2,
                y + height / 2,
            ),
            radius=S(6),
            outline=MUTED,
            width=S(2),
        )

        font = self.font_pill

        draw.text(
            (
                cx,
                y,
            ),
            '"',
            font=font,
            fill=MUTED,
            anchor="mm",
        )

        # Queue
        cx = BOTTOM_ICON3_X

        for dy in (
            -S(9),
            0,
            S(9),
        ):

            dot = S(2)

            x0 = (
                cx
                - S(15)
            )

            draw.ellipse(
                (
                    x0 - dot,
                    y + dy - dot,
                    x0 + dot,
                    y + dy + dot,
                ),
                fill=MUTED,
            )

            draw.line(
                (
                    x0 + S(8),
                    y + dy,
                    x0 + S(34),
                    y + dy,
                ),
                fill=MUTED,
                width=S(2),
            )


    # ========================================================
    # RIGHT PANEL
    # ========================================================

    def draw_now_playing(
        self,
        canvas,
        title,
        channel,
        bot_name,
        duration,
    ):

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        max_title_width = (
            STAR_ICON_X
            - TOP_ICON_R
            - RIGHT_X
            - S(24)
        )

        title = unidecode(
            str(title or "Unknown Title")
        )

        title, title_font = self.fit_title(
            draw,
            title,
            max_title_width,
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

        channel = unidecode(
            str(channel or "Unknown Artist")
        )

        draw.text(
            (
                RIGHT_X,
                SUBTITLE_Y,
            ),
            self.truncate(
                channel,
                34,
            ),
            font=self.font_subtitle,
            fill=SUBTITLE_COLOR,
        )

        # Icons
        self.draw_star(
            canvas,
            STAR_ICON_X,
            TOP_ICON_Y,
            TOP_ICON_R,
        )

        self.draw_overflow(
            canvas,
            DOTS_ICON_X,
            TOP_ICON_Y,
            TOP_ICON_R,
        )

        # Duration
        total = self.parse_duration(
            duration
        )

        elapsed_seconds = 3

        if total and total > 0:

            fraction = max(
                0,
                min(
                    1,
                    elapsed_seconds / total,
                ),
            )

            remaining = max(
                0,
                total - elapsed_seconds,
            )

            remaining_text = (
                "-"
                + self.format_time(
                    remaining
                )
            )

        else:

            fraction = 0.02
            remaining_text = None

        self.draw_seekbar(
            canvas,
            fraction,
        )

        self.draw_time_row(
            canvas,
            self.format_time(
                elapsed_seconds
            ),
            remaining_text,
            bot_name,
        )

        self.draw_controls(
            canvas
        )

        self.draw_volume(
            canvas
        )

        self.draw_bottom_icons(
            canvas
        )


    # ========================================================
    # FINAL COMPOSE
    # ========================================================

    def compose(
        self,
        cover,
        title,
        channel,
        bot_name,
        duration=None,
    ):

        cover = cover.convert("RGB")

        accent = self.get_accent(
            cover
        )

        canvas = self.build_background(
            cover
        )

        self.draw_poster_card(
            canvas,
            cover,
            accent,
        )

        self.draw_now_playing(
            canvas,
            title,
            channel,
            bot_name,
            duration,
        )

        # Very subtle grain
        grain = Image.new(
            "RGBA",
            FINAL_SIZE,
            (128, 128, 128, 5),
        )

        canvas.alpha_composite(
            grain
        )

        result = canvas.convert(
            "RGB"
        )

        canvas.close()
        cover.close()

        return result


# ============================================================
# SINGLE GLOBAL THUMBNAIL INSTANCE
# ============================================================

thumbnail_generator = Thumbnail()


# ============================================================
# MAIN FUNCTION
# KEEPING FIRST CODE'S SAME API
# ============================================================

async def get_thumb(
    videoid,
    user_id,
    title=None,
    duration=None,
    thumbnail=None,
    views=None,
    channel=None,
):

    cache_dir = "cache"

    os.makedirs(
        cache_dir,
        exist_ok=True,
    )

    output_path = (
        f"{cache_dir}/{videoid}_{user_id}.png"
    )

    # Existing cached thumbnail
    if os.path.isfile(output_path):
        return output_path

    cover_path = (
        f"{cache_dir}/thumb_{videoid}.jpg"
    )

    try:

        # ====================================================
        # FETCH YOUTUBE DETAILS
        # ====================================================

        if not title or not thumbnail:

            url = (
                f"https://www.youtube.com/watch?v={videoid}"
            )

            results = VideosSearch(
                url,
                limit=1,
            )

            data = await results.next()

            items = data.get(
                "result",
                [],
            )

            if not items:
                return YOUTUBE_IMG_URL

            result = items[0]

            try:
                title = result.get(
                    "title",
                    "Unknown Title",
                )
            except Exception:
                title = "Unknown Title"

            try:
                duration = result.get(
                    "duration",
                    "Unknown",
                )
            except Exception:
                duration = "Unknown"

            try:
                thumbnail = result[
                    "thumbnails"
                ][0]["url"].split("?")[0]
            except Exception:
                thumbnail = YOUTUBE_IMG_URL

            try:
                channel = result[
                    "channel"
                ]["name"]
            except Exception:
                channel = "Unknown Artist"

            try:
                views = result[
                    "viewCount"
                ]["short"]
            except Exception:
                views = "Unknown Views"

        else:

            title = str(
                title or "Unknown Title"
            )

            duration = (
                duration
                or "Unknown"
            )

            channel = (
                channel
                or "Unknown Artist"
            )

        # ====================================================
        # DOWNLOAD COVER
        # ====================================================

        try:

            await download_file(
                thumbnail,
                cover_path,
            )

        except Exception:

            # If supplied thumbnail fails,
            # try YouTube default image.
            if thumbnail != YOUTUBE_IMG_URL:

                try:
                    await download_file(
                        YOUTUBE_IMG_URL,
                        cover_path,
                    )
                except Exception:
                    return YOUTUBE_IMG_URL

            else:
                return YOUTUBE_IMG_URL

        # ====================================================
        # LOAD COVER
        # ====================================================

        cover = await asyncio.to_thread(
            load_image,
            cover_path,
        )

        if cover is None:
            return YOUTUBE_IMG_URL

        # ====================================================
        # BOT NAME
        # ====================================================

        try:
            bot_name = unidecode(
                str(
                    app.name
                    or "Music Bot"
                )
            )
        except Exception:
            bot_name = "Music Bot"

        # ====================================================
        # GENERATE 1920x1080 THUMBNAIL
        # ====================================================

        final_image = await asyncio.to_thread(
            thumbnail_generator.compose,
            cover,
            title,
            channel,
            bot_name,
            duration,
        )

        # ====================================================
        # SAVE
        # ====================================================

        await asyncio.to_thread(
            final_image.save,
            output_path,
            "PNG",
            optimize=True,
        )

        try:
            final_image.close()
        except Exception:
            pass

        try:
            cover.close()
        except Exception:
            pass

        return output_path

    except Exception as e:

        print(
            f"[Thumbnail Error] {type(e).__name__}: {e}"
        )

        return YOUTUBE_IMG_URL

    finally:

        try:
            if os.path.exists(cover_path):
                os.remove(cover_path)
        except Exception:
            pass
