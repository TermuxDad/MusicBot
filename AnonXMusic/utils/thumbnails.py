import asyncio
import colorsys
import math
import os
from pathlib import Path
import random
import tempfile
import uuid
from types import SimpleNamespace

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


_MODULE_DIR = Path(__file__).resolve().parent
_ASSETS_DIR = _MODULE_DIR.parent / "assets"


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fw:
        fw.write(data)


FINAL_SIZE = (1920, 1080)
CANVAS_SIZE = FINAL_SIZE
W, H = CANVAS_SIZE

_BASE_W = 1280
RATIO = FINAL_SIZE[0] / _BASE_W


def S(v):
    """Scale a size / coordinate / tuple to the current FINAL_SIZE."""
    if isinstance(v, (tuple, list)):
        return tuple(S(x) for x in v)
    return int(round(v * RATIO))


CARD_BOX = S((90, 90, 610, 610))
CARD_RADIUS = S(24)

RIGHT_X = S(716)
RIGHT_X_END = S(1200)
RIGHT_MAX_W = RIGHT_X_END - RIGHT_X

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
PLAY_R = S(54)
FORWARD_X = S(1116)

VOLUME_Y = S(553)
VOL_SPEAKER_LOW_X = S(731)
VOL_BAR_X0 = S(766)
VOL_BAR_X1 = S(1138)
VOL_SPEAKER_HIGH_X = S(1172)
VOL_FRACTION = 0.72

BOTTOM_ICON_Y = S(635)
BOTTOM_ICON1_X = S(774)
BOTTOM_ICON3_X = S(1131)

COL_WHITE = (255, 255, 255)
COL_TITLE = (255, 255, 255)
COL_SUBTITLE = (222, 222, 222)
COL_MUTED = (185, 185, 185)
GOLD = (224, 176, 92)
TRACK_BG = (255, 255, 255, 80)
ACCENT_FALLBACK = (224, 176, 92)


class Thumbnail:
    def __init__(self):
        self.title_font_path = str(
            _ASSETS_DIR / "Poppins-ExtraBold.ttf"
        )
        self.subtitle_font_path = str(
            _ASSETS_DIR / "Raleway-Bold.ttf"
        )

        if not os.path.isfile(self.title_font_path):
            raise FileNotFoundError(
                f"Missing thumbnail font: {self.title_font_path}"
            )

        if not os.path.isfile(self.subtitle_font_path):
            raise FileNotFoundError(
                f"Missing thumbnail font: {self.subtitle_font_path}"
            )

        self.font_subtitle = ImageFont.truetype(
            self.subtitle_font_path, S(24)
        )
        self.font_time = ImageFont.truetype(
            self.subtitle_font_path, S(20)
        )
        self.font_pill = ImageFont.truetype(
            self.subtitle_font_path, S(17)
        )

        self._grain_cache_key = None
        self._grain_alpha_cache = None

    # ---------- generic helpers ----------

    async def save_thumb(self, output_path: str, url: str) -> str:
        """Download a thumbnail safely and return its local path."""

        if not isinstance(url, str) or not url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                f"Invalid thumbnail URL: {url!r}"
            )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        timeout = aiohttp.ClientTimeout(
            total=20,
            connect=8,
            sock_read=15,
        )

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
                ).lower()

                if "image" not in content_type:
                    try:
                        import io

                        with Image.open(
                            io.BytesIO(data)
                        ) as image:
                            image.verify()

                    except Exception as exc:
                        raise ValueError(
                            "Thumbnail URL did not return "
                            f"a valid image "
                            f"(status={resp.status}, "
                            f"content_type={content_type!r})"
                        ) from exc

        await asyncio.to_thread(
            _write_bytes,
            output_path,
            data,
        )

        return output_path

    def load_avatar(self, source):
        """Open a local file or PIL Image as RGB."""

        try:
            img = (
                source
                if isinstance(source, Image.Image)
                else Image.open(source)
            )

            return img.convert("RGB")

        except Exception:
            return None

    async def fetch_avatar(self, url, tmp_path):
        """Download and decode a profile photo safely."""

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        timeout = aiohttp.ClientTimeout(
            total=20,
            connect=8,
            sock_read=15,
        )

        try:
            async with aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            ) as session:
                async with session.get(
                    url,
                    allow_redirects=True,
                ) as resp:
                    resp.raise_for_status()

                    content_type = resp.headers.get(
                        "Content-Type",
                        "",
                    ).lower()

                    data = await resp.read()

                    valid_signatures = (
                        b"\xff\xd8\xff",
                        b"\x89PNG",
                        b"GIF8",
                        b"RIFF",
                    )

                    if (
                        "image" not in content_type
                        and not data.startswith(valid_signatures)
                    ):
                        print(
                            "[fetch_avatar] URL did not return "
                            f"an image "
                            f"(content-type={content_type!r}): "
                            f"{url}"
                        )
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
                f"[fetch_avatar] failed for {url}: {e!r}"
            )
            return None

    def fit_image(self, image, size):
        return ImageOps.fit(
            image,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    def add_round_corners(self, image, radius):
        rounded = image.convert("RGBA")
        w, h = rounded.size

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

        output = Image.new(
            "RGBA",
            (w, h),
            (0, 0, 0, 0),
        )

        output.paste(
            rounded,
            (0, 0),
            mask,
        )

        return output

    def fit_title_font(
        self,
        draw,
        text,
        max_width,
        base_size,
        min_size,
    ):
        size = base_size

        while size > min_size:
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

    def fit_title_text_and_font(
        self,
        draw,
        text,
        max_width,
        base_size,
        min_size,
    ):
        font = self.fit_title_font(
            draw,
            text,
            max_width,
            base_size,
            min_size,
        )

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font,
        )

        while (
            bbox[2] - bbox[0] > max_width
            and len(text) > 8
        ):
            text = text[:-4].rstrip() + "..."

            bbox = draw.textbbox(
                (0, 0),
                text,
                font=font,
            )

        return text, font

    def truncate(
        self,
        text: str,
        limit: int,
    ) -> str:
        text = text or ""

        return (
            text[: limit - 3] + "..."
            if len(text) > limit
            else text
        )

    @staticmethod
    def _format_time(seconds):
        if seconds is None or seconds < 0:
            return None

        seconds = int(seconds)

        m, s = divmod(
            seconds,
            60,
        )

        return f"{m}:{s:02d}"

    def accent_from_cover(self, cover_img):
        """Get a vivid accent color from cover art."""

        small = (
            cover_img
            .convert("RGB")
            .resize((60, 60))
        )

        quant = small.quantize(
            colors=6,
            method=Image.MEDIANCUT,
        )

        palette = quant.getpalette()[: 6 * 3]

        counts = sorted(
            quant.getcolors() or [],
            key=lambda c: -c[0],
        )

        if counts:
            _, idx = counts[0]

            r, g, b = palette[
                idx * 3: idx * 3 + 3
            ]

        else:
            r, g, b = ACCENT_FALLBACK

        h, s, v = colorsys.rgb_to_hsv(
            r / 255,
            g / 255,
            b / 255,
        )

        s = min(
            max(s, 0.6),
            0.92,
        )

        v = min(
            max(v, 0.6),
            0.88,
        )

        rr, gg, bb = colorsys.hsv_to_rgb(
            h,
            s,
            v,
        )

        return (
            int(rr * 255),
            int(gg * 255),
            int(bb * 255),
        )

    # ---------- background ----------

    def build_background(self, cover_img):
        bg = self.fit_image(
            cover_img,
            CANVAS_SIZE,
        )

        bg = bg.filter(
            ImageFilter.GaussianBlur(
                radius=S(32)
            )
        )

        bg = ImageEnhance.Brightness(
            bg
        ).enhance(0.28)

        bg = ImageEnhance.Contrast(
            bg
        ).enhance(1.12)

        canvas = bg.convert("RGBA")

        overlay = Image.new(
            "RGBA",
            CANVAS_SIZE,
            (0, 0, 0, 125),
        )

        canvas.alpha_composite(
            overlay
        )

        return canvas

    # ---------- poster ----------

    def draw_poster_card(
        self,
        canvas,
        cover_img,
        accent,
    ):
        card_w = CARD_BOX[2] - CARD_BOX[0]
        card_h = CARD_BOX[3] - CARD_BOX[1]

        poster = self.fit_image(
            cover_img,
            (card_w, card_h),
        )

        poster = self.add_round_corners(
            poster,
            CARD_RADIUS,
        )

        canvas.alpha_composite(
            poster,
            (CARD_BOX[0], CARD_BOX[1]),
        )

        glow = Image.new(
            "RGBA",
            CANVAS_SIZE,
            (0, 0, 0, 0),
        )

        glow_draw = ImageDraw.Draw(
            glow
        )

        gx = CARD_BOX[0] + card_w // 2
        gy = CARD_BOX[1] + card_h // 2

        for radius in range(
            S(350),
            S(40),
            -S(25),
        ):
            alpha = int(
                2
                + 20
                * (
                    1
                    - radius
                    / S(350)
                )
            )

            glow_draw.ellipse(
                (
                    gx - radius,
                    gy - radius,
                    gx + radius,
                    gy + radius,
                ),
                fill=(
                    accent[0],
                    accent[1],
                    accent[2],
                    alpha,
                ),
            )

        glow = glow.filter(
            ImageFilter.GaussianBlur(
                S(30)
            )
        )

        canvas.alpha_composite(
            glow
        )

    # ---------- right panel ----------

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
            canvas
        )

        title = str(
            title or "Unknown Title"
        )

        channel_name = str(
            channel_name or "Unknown"
        )

        bot_name = str(
            bot_name or "Music Bot"
        )

        title, title_font = (
            self.fit_title_text_and_font(
                draw,
                title,
                RIGHT_MAX_W,
                S(52),
                S(28),
            )
        )

        draw.text(
            (
                RIGHT_X,
                TITLE_Y,
            ),
            title,
            font=title_font,
            fill=COL_TITLE,
        )

        subtitle = self.truncate(
            channel_name,
            34,
        )

        draw.text(
            (
                RIGHT_X,
                SUBTITLE_Y,
            ),
            subtitle,
            font=self.font_subtitle,
            fill=COL_SUBTITLE,
        )

        # top star
        draw.ellipse(
            (
                STAR_ICON_X - TOP_ICON_R,
                TOP_ICON_Y - TOP_ICON_R,
                STAR_ICON_X + TOP_ICON_R,
                TOP_ICON_Y + TOP_ICON_R,
            ),
            outline=COL_MUTED,
            width=S(2),
        )

        # top dots
        for i in range(3):
            draw.ellipse(
                (
                    DOTS_ICON_X - S(3),
                    TOP_ICON_Y - S(13)
                    + i * S(13),
                    DOTS_ICON_X + S(3),
                    TOP_ICON_Y - S(7)
                    + i * S(13),
                ),
                fill=COL_MUTED,
            )

        # seek bar
        seek_x0 = RIGHT_X
        seek_x1 = RIGHT_X_END

        draw.rounded_rectangle(
            (
                seek_x0,
                SEEK_Y - S(4),
                seek_x1,
                SEEK_Y + S(4),
            ),
            radius=S(4),
            fill=TRACK_BG,
        )

        if duration and duration > 0:
            progress = max(
                0.0,
                min(
                    float(elapsed or 0)
                    / float(duration),
                    1.0,
                ),
            )
        else:
            progress = 0.0

        seek_current = int(
            seek_x0
            + (
                seek_x1 - seek_x0
            )
            * progress
        )

        draw.rounded_rectangle(
            (
                seek_x0,
                SEEK_Y - S(4),
                seek_current,
                SEEK_Y + S(4),
            ),
            radius=S(4),
            fill=GOLD,
        )

        draw.ellipse(
            (
                seek_current - SEEK_THUMB_R,
                SEEK_Y - SEEK_THUMB_R,
                seek_current + SEEK_THUMB_R,
                SEEK_Y + SEEK_THUMB_R,
            ),
            fill=GOLD,
        )

        elapsed_text = self._format_time(
            elapsed
        ) or "0:00"

        if duration and duration > 0:
            remaining = max(
                0,
                int(duration - (elapsed or 0)),
            )

            remaining_text = (
                "-"
                + self._format_time(
                    remaining
                )
            )
        else:
            remaining_text = "-0:00"

        draw.text(
            (
                RIGHT_X,
                TIME_Y,
            ),
            elapsed_text,
            font=self.font_time,
            fill=COL_MUTED,
        )

        bbox = draw.textbbox(
            (0, 0),
            remaining_text,
            font=self.font_time,
        )

        draw.text(
            (
                RIGHT_X_END
                - (
                    bbox[2] - bbox[0]
                ),
                TIME_Y,
            ),
            remaining_text,
            font=self.font_time,
            fill=COL_MUTED,
        )

        # Bot pill
        pill_w = S(170)
        pill_h = PILL_H

        pill_box = (
            PILL_CX - pill_w // 2,
            TIME_Y - S(2),
            PILL_CX + pill_w // 2,
            TIME_Y - S(2) + pill_h,
        )

        draw.rounded_rectangle(
            pill_box,
            radius=S(18),
            fill=(
                255,
                255,
                255,
                28,
            ),
            outline=(
                255,
                255,
                255,
                45,
            ),
            width=S(1),
        )

        pill_text = self.truncate(
            bot_name,
            16,
        )

        bbox = draw.textbbox(
            (0, 0),
            pill_text,
            font=self.font_pill,
        )

        draw.text(
            (
                PILL_CX
                - (bbox[2] - bbox[0]) // 2,
                pill_box[1] + S(7),
            ),
            pill_text,
            font=self.font_pill,
            fill=COL_WHITE,
        )

        # rewind
        draw.polygon(
            [
                (
                    REWIND_X,
                    CONTROLS_Y,
                ),
                (
                    REWIND_X + S(24),
                    CONTROLS_Y - S(20),
                ),
                (
                    REWIND_X + S(24),
                    CONTROLS_Y + S(20),
                ),
            ],
            fill=COL_WHITE,
        )

        draw.polygon(
            [
                (
                    REWIND_X + S(22),
                    CONTROLS_Y,
                ),
                (
                    REWIND_X + S(46),
                    CONTROLS_Y - S(20),
                ),
                (
                    REWIND_X + S(46),
                    CONTROLS_Y + S(20),
                ),
            ],
            fill=COL_WHITE,
        )

        # play circle
        draw.ellipse(
            (
                PLAY_CX - PLAY_R,
                CONTROLS_Y - PLAY_R,
                PLAY_CX + PLAY_R,
                CONTROLS_Y + PLAY_R,
            ),
            fill=GOLD,
        )

        draw.polygon(
            [
                (
                    PLAY_CX - S(10),
                    CONTROLS_Y - S(18),
                ),
                (
                    PLAY_CX + S(20),
                    CONTROLS_Y,
                ),
                (
                    PLAY_CX - S(10),
                    CONTROLS_Y + S(18),
                ),
            ],
            fill=COL_WHITE,
        )

        # forward
        draw.polygon(
            [
                (
                    FORWARD_X,
                    CONTROLS_Y,
                ),
                (
                    FORWARD_X - S(24),
                    CONTROLS_Y - S(20),
                ),
                (
                    FORWARD_X - S(24),
                    CONTROLS_Y + S(20),
                ),
            ],
            fill=COL_WHITE,
        )

        draw.polygon(
            [
                (
                    FORWARD_X - S(22),
                    CONTROLS_Y,
                ),
                (
                    FORWARD_X - S(46),
                    CONTROLS_Y - S(20),
                ),
                (
                    FORWARD_X - S(46),
                    CONTROLS_Y + S(20),
                ),
            ],
            fill=COL_WHITE,
        )

        # volume bar
        draw.rounded_rectangle(
            (
                VOL_BAR_X0,
                VOLUME_Y - S(4),
                VOL_BAR_X1,
                VOLUME_Y + S(4),
            ),
            radius=S(4),
            fill=TRACK_BG,
        )

        vol_end = int(
            VOL_BAR_X0
            + (
                VOL_BAR_X1
                - VOL_BAR_X0
            )
            * VOL_FRACTION
        )

        draw.rounded_rectangle(
            (
                VOL_BAR_X0,
                VOLUME_Y - S(4),
                vol_end,
                VOLUME_Y + S(4),
            ),
            radius=S(4),
            fill=GOLD,
        )

        draw.ellipse(
            (
                vol_end - S(8),
                VOLUME_Y - S(8),
                vol_end + S(8),
                VOLUME_Y + S(8),
            ),
            fill=GOLD,
        )

        # bottom icons
        draw.arc(
            (
                BOTTOM_ICON1_X - S(18),
                BOTTOM_ICON_Y - S(14),
                BOTTOM_ICON1_X + S(18),
                BOTTOM_ICON_Y + S(14),
            ),
            start=200,
            end=340,
            fill=COL_MUTED,
            width=S(3),
        )

        draw.line(
            (
                BOTTOM_ICON1_X - S(12),
                BOTTOM_ICON_Y,
                BOTTOM_ICON1_X + S(12),
                BOTTOM_ICON_Y,
            ),
            fill=COL_MUTED,
            width=S(3),
        )

        for i in range(3):
            y = (
                BOTTOM_ICON_Y
                - S(12)
                + i * S(12)
            )

            draw.line(
                (
                    BOTTOM_ICON3_X - S(16),
                    y,
                    BOTTOM_ICON3_X + S(16),
                    y,
                ),
                fill=COL_MUTED,
                width=S(3),
            )

    # ---------- grain ----------

    def apply_grain(
        self,
        image,
        opacity=8,
    ):
        key = (
            image.size,
            int(opacity),
        )

        if (
            self._grain_cache_key == key
            and self._grain_alpha_cache is not None
        ):
            noise = self._grain_alpha_cache
        else:
            noise = Image.effect_noise(
                image.size,
                128,
            ).convert("L")

            self._grain_cache_key = key
            self._grain_alpha_cache = noise

        grain = Image.new(
            "RGBA",
            image.size,
            (255, 255, 255, 0),
        )

        grain.putalpha(
            noise.point(
                lambda p: int(
                    abs(p - 128)
                    * opacity
                    / 128
                )
            )
        )

        image.alpha_composite(
            grain
        )

    # ---------- full compose ----------

    def compose(
        self,
        cover_img,
        title: str,
        channel_name: str,
        bot_name: str,
        avatar_img=None,
        duration=None,
        elapsed=3,
        **_ignored,
    ) -> Image.Image:
        converted_cover = cover_img.convert(
            "RGB"
        )

        accent = self.accent_from_cover(
            converted_cover
        )

        canvas = self.build_background(
            converted_cover
        )

        self.draw_poster_card(
            canvas,
            converted_cover,
            accent,
        )

        self.draw_now_playing_panel(
            canvas,
            title,
            channel_name,
            bot_name,
            avatar_img=avatar_img,
            duration=duration,
            elapsed=elapsed,
        )

        self.apply_grain(
            canvas,
            opacity=8,
        )

        final = canvas.convert(
            "RGB"
        )

        canvas.close()
        converted_cover.close()

        return final

    # ---------- bot-facing async entrypoint ----------

    @staticmethod
    def _parse_duration(value):
        if value is None:
            return None

        if isinstance(
            value,
            (int, float),
        ):
            return float(value)

        if isinstance(value, str):
            text = value.strip()

            if ":" in text:
                parts = text.split(":")

                try:
                    parts = [
                        int(p)
                        for p in parts
                    ]
                except ValueError:
                    return None

                seconds = 0

                for p in parts:
                    seconds = (
                        seconds * 60
                        + p
                    )

                return float(seconds)

            try:
                return float(text)
            except ValueError:
                return None

        return None

    @staticmethod
    def _first_attr(
        obj,
        *names,
        default=None,
    ):
        for name in names:
            val = getattr(
                obj,
                name,
                None,
            )

            if val:
                return val

        return default

    async def generate(
        self,
        media,
        output_path: str = None,
        user_avatar=None,
    ) -> str:

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
                "generate(): could not find a "
                "cover/thumbnail URL on the given "
                f"media object "
                f"({type(media).__name__!r}); "
                "expected one of: thumb, thumbnail, "
                "cover, cover_url, image, photo, "
                "photo_url, art, artwork"
            )

        title = self._first_attr(
            media,
            "title",
            "name",
            default="Unknown Title",
        )

        channel_name = self._first_attr(
            media,
            "channel",
            "channel_name",
            "uploader",
            "artist",
            "user",
            default="Unknown",
        )

        bot_name = (
            getattr(app, "name", None)
            or "Music Bot"
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

        duration = self._parse_duration(
            duration
        )

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

        if not output_path:
            media_id = self._first_attr(
                media,
                "id",
                default=uuid.uuid4().hex,
            )

            output_path = os.path.join(
                "cache",
                f"thumb_{media_id}.jpg",
            )

        os.makedirs(
            os.path.dirname(output_path)
            or ".",
            exist_ok=True,
        )

        tmp_cover = (
            f"{output_path}.cover_tmp.jpg"
        )

        tmp_avatar = (
            f"{output_path}.avatar_tmp.jpg"
        )

        avatar_img = None
        cover_img = None
        final_img = None

        try:
            cover_task = asyncio.create_task(
                self.save_thumb(
                    tmp_cover,
                    cover_url,
                )
            )

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
                    avatar_img = (
                        await asyncio.to_thread(
                            self.load_avatar,
                            resolved,
                        )
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
                    avatar_img = (
                        await self.fetch_avatar(
                            resolved,
                            tmp_avatar,
                        )
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
                avatar_img = (
                    await asyncio.to_thread(
                        self.load_avatar,
                        avatar_source,
                    )
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
                avatar_img = (
                    await self.fetch_avatar(
                        avatar_source,
                        tmp_avatar,
                    )
                )

            await cover_task

            cover_img = await asyncio.to_thread(
                self.load_avatar,
                tmp_cover,
            )

            if cover_img is None:
                raise ValueError(
                    "Failed to load cover image "
                    f"from {cover_url}"
                )

            final_img = await asyncio.to_thread(
                self.compose,
                cover_img,
                title,
                channel_name,
                bot_name,
                avatar_img=avatar_img,
                duration=duration,
            )

            await asyncio.to_thread(
                final_img.save,
                output_path,
                quality=90,
            )

        finally:
            for img in (
                avatar_img,
                cover_img,
                final_img,
            ):
                if img and hasattr(
                    img,
                    "close",
                ):
                    try:
                        img.close()
                    except Exception:
                        pass

            for tmp in (
                tmp_cover,
                tmp_avatar,
            ):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

            import gc

            gc.collect()

        return output_path


# MusicBot compatibility wrapper.
# Existing MusicBot plugins call:
# await get_thumb(videoid, user_id)

async def get_thumb(
    videoid,
    user_id,
    title=None,
    duration=None,
    thumbnail=None,
    views=None,
    channel=None,
):
    output_path = os.path.join(
        "cache",
        f"{videoid}_{user_id}.jpg",
    )

    if os.path.isfile(output_path):
        return output_path

    try:
        if not title or not thumbnail:
            url = (
                f"https://www.youtube.com/watch?v={videoid}"
            )

            results = VideosSearch(
                url,
                limit=1,
            )

            data = (
                await results.next()
            ).get(
                "result",
                [],
            )

            if not data:
                return YOUTUBE_IMG_URL

            result = data[0]

            title = (
                title
                or result.get("title")
                or "Unknown Title"
            )

            thumbnail = (
                thumbnail
                or result.get(
                    "thumbnails",
                    [{}],
                )[0].get(
                    "url",
                    "",
                ).split("?")[0]
            )

            duration = (
                duration
                or result.get("duration")
                or "Unknown"
            )

            channel = (
                channel
                or result.get(
                    "channel",
                    {},
                ).get("name")
                or "Unknown"
            )

            views = (
                views
                or result.get(
                    "viewCount",
                    {},
                ).get("short")
                or "Unknown Views"
            )

        if not thumbnail:
            return YOUTUBE_IMG_URL

        media = SimpleNamespace(
            id=f"{videoid}_{user_id}",
            title=str(title),
            thumb=thumbnail,
            channel=channel or "Unknown",
            duration=duration,
            views=views,
        )

        thumb = Thumbnail()

        return await thumb.generate(
            media,
            output_path=output_path,
        )

    except Exception as e:
        print(
            f"[get_thumb] thumbnail generation "
            f"failed: {e!r}"
        )

        return YOUTUBE_IMG_URL
