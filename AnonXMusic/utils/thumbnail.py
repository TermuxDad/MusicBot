
import asyncio
import colorsys
import math
import os
import random
import tempfile
import uuid

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from auro import config


FINAL_SIZE = (1920, 1080)
W, H = FINAL_SIZE
BASE_W = 1280
RATIO = W / BASE_W

COL_WHITE = (255, 255, 255, 255)
COL_SUBTITLE = (225, 225, 225, 255)
COL_MUTED = (190, 190, 190, 255)
ACCENT_FALLBACK = (224, 176, 92)


def S(value):
    if isinstance(value, (tuple, list)):
        return tuple(S(x) for x in value)
    return int(round(float(value) * RATIO))


def _write_bytes(path, data):
    with open(path, "wb") as file:
        file.write(data)


def _font(path, size, fallback=None):
    try:
        return ImageFont.truetype(path, max(8, int(size)))
    except Exception:
        if fallback:
            try:
                return ImageFont.truetype(fallback, max(8, int(size)))
            except Exception:
                pass
        return ImageFont.load_default()


class Thumbnail:
    def __init__(self):
        base = os.path.dirname(__file__)
        self.font_dir = base

        self.title_font_path = os.path.join(base, "Poppins-ExtraBold.ttf")
        self.subtitle_font_path = os.path.join(base, "Raleway-Bold.ttf")

        self.default_font = _font(self.title_font_path, S(46))
        self.font_subtitle = _font(self.subtitle_font_path, S(24))
        self.font_time = _font(self.subtitle_font_path, S(20))
        self.font_pill = _font(self.subtitle_font_path, S(17))

        self._grain_cache_key = None
        self._grain_alpha_cache = None

        self.card_box = S((90, 90, 610, 610))
        self.card_radius = S(24)

        self.right_x = S(716)
        self.right_end = S(1200)
        self.title_y = S(149)
        self.subtitle_y = S(211)

        self.top_icon_y = S(168)
        self.top_icon_r = S(24)
        self.star_x = S(1109)
        self.dots_x = S(1181)

        self.seek_y = S(274)
        self.seek_thumb_r = S(9)

        self.time_y = S(314)
        self.pill_cx = S(952)
        self.pill_h = S(34)

        self.controls_y = S(434)
        self.rewind_x = S(791)
        self.play_cx = S(952)
        self.forward_x = S(1116)

        self.volume_y = S(553)
        self.vol_low_x = S(731)
        self.vol_x0 = S(766)
        self.vol_x1 = S(1138)
        self.vol_high_x = S(1172)

        self.bottom_y = S(635)
        self.bottom_left_x = S(774)
        self.bottom_right_x = S(1131)

    async def save_thumb(self, output_path, url):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            headers=headers, timeout=timeout
        ) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                data = await response.read()

        if not data:
            raise ValueError("Thumbnail URL returned empty data.")

        await asyncio.to_thread(_write_bytes, output_path, data)
        return output_path

    @staticmethod
    def load_image(source):
        try:
            if isinstance(source, Image.Image):
                image = source.copy()
            else:
                image = Image.open(source)
                image.load()
            return image.convert("RGB")
        except Exception:
            return None

    async def fetch_avatar(self, url, tmp_path):
        try:
            await self.save_thumb(tmp_path, url)
            return await asyncio.to_thread(self.load_image, tmp_path)
        except Exception as exc:
            print(f"[Thumbnail] avatar download failed: {exc}")
            return None

    @staticmethod
    def fit_image(image, size):
        return ImageOps.fit(
            image.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    @staticmethod
    def round_image(image, radius):
        image = image.convert("RGBA")
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=max(1, int(radius)),
            fill=255,
        )
        result = Image.new("RGBA", image.size, (0, 0, 0, 0))
        result.paste(image, (0, 0), mask)
        return result

    @staticmethod
    def truncate(text, limit):
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 3)].rstrip() + "..."

    @staticmethod
    def parse_duration(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if value >= 0 else None
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        if ":" in value:
            try:
                result = 0
                for part in value.split(":"):
                    result = result * 60 + int(part)
                return float(result)
            except (ValueError, TypeError):
                return None

        try:
            result = float(value)
            return result if result >= 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def first_attr(obj, *names, default=None):
        for name in names:
            try:
                value = getattr(obj, name, None)
            except Exception:
                value = None
            if value is not None and value != "":
                return value
        return default

    @staticmethod
    def format_time(seconds):
        try:
            seconds = int(max(0, float(seconds)))
        except (TypeError, ValueError):
            return None
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def accent_from_cover(self, image):
        try:
            small = image.convert("RGB").resize((64, 64))
            quantized = small.quantize(colors=8)
            colors = quantized.getcolors()
            palette = quantized.getpalette()
            if not colors or not palette:
                return ACCENT_FALLBACK

            _, index = max(colors, key=lambda item: item[0])
            r, g, b = palette[index * 3:index * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            s = max(0.55, min(0.92, s))
            v = max(0.55, min(0.88, v))
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            return int(r * 255), int(g * 255), int(b * 255)
        except Exception:
            return ACCENT_FALLBACK

    def build_background(self, cover):
        image = cover.convert("RGB")
        zoom_size = (int(W * 1.18), int(H * 1.18))
        zoomed = ImageOps.fit(
            image,
            zoom_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        left = max(0, (zoomed.width - W) // 2)
        top = max(0, (zoomed.height - H) // 2)
        background = zoomed.crop((left, top, left + W, top + H))
        zoomed.close()

        small = background.resize((max(1, W // 5), max(1, H // 5)))
        background.close()
        background = small.resize((W, H), Image.Resampling.BILINEAR)
        small.close()

        background = background.filter(ImageFilter.GaussianBlur(S(24)))
        background = ImageEnhance.Color(background).enhance(1.08)
        background = ImageEnhance.Contrast(background).enhance(1.02)
        background = ImageEnhance.Brightness(background).enhance(0.72)
        canvas = background.convert("RGBA")
        background.close()

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 105))
        canvas.alpha_composite(overlay)
        overlay.close()

        # Slightly darker right side so controls remain readable.
        right = Image.new("L", (W, 1), 0)
        pixels = right.load()
        start = self.card_box[2]
        for x in range(W):
            pixels[x, 0] = int(
                75 * max(0.0, min(1.0, (x - start) / max(1, S(180))))
            )
        right = right.resize((W, H))
        right_layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        right_layer.putalpha(right)
        canvas.alpha_composite(right_layer)
        right.close()
        right_layer.close()

        return canvas

    def draw_glow(self, canvas, accent):
        x0, y0, x1, y1 = self.card_box
        small = (max(1, W // 4), max(1, H // 4))
        glow = Image.new("RGBA", small, (0, 0, 0, 0))
        draw = ImageDraw.Draw(glow)
        draw.ellipse(
            (
                x0 / 4,
                y0 / 4,
                x1 / 4,
                y1 / 4,
            ),
            fill=(*accent, 55),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(max(2, S(45) // 4)))
        glow = glow.resize((W, H), Image.Resampling.BILINEAR)

        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rectangle(
            (0, 0, self.right_x - S(50), H), fill=255
        )
        alpha = glow.getchannel("A")
        alpha = Image.composite(alpha, Image.new("L", (W, H), 0), mask)
        glow.putalpha(alpha)
        canvas.alpha_composite(glow)
        glow.close()
        mask.close()

    def draw_card(self, canvas, cover, accent):
        self.draw_glow(canvas, accent)

        x0, y0, x1, y1 = self.card_box
        width = x1 - x0
        height = y1 - y0

        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x0 + S(6), y0 + S(16), x1 + S(6), y1 + S(16)),
            radius=self.card_radius,
            fill=(0, 0, 0, 145),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(S(22)))
        canvas.alpha_composite(shadow)
        shadow.close()

        art = self.fit_image(cover, (width, height))
        art = self.round_image(art, self.card_radius)

        border = Image.new("RGBA", art.size, (0, 0, 0, 0))
        ImageDraw.Draw(border).rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=self.card_radius,
            outline=(255, 255, 255, 90),
            width=max(1, S(1)),
        )
        art.alpha_composite(border)
        border.close()

        canvas.alpha_composite(art, (x0, y0))
        art.close()

    def fit_title(self, draw, text, max_width):
        size = S(46)
        minimum = S(24)
        text = self.truncate(text, 42)

        while size >= minimum:
            font = _font(self.title_font_path, size)
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_width:
                return text, font
            size -= S(2)

        font = _font(self.title_font_path, minimum)
        while len(text) > 8:
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_width:
                break
            text = text[:-4].rstrip() + "..."
        return text, font

    def circle_button(self, canvas, cx, cy, radius):
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(35, 35, 35, 170),
            outline=(255, 255, 255, 220),
            width=max(1, S(1)),
        )

    def draw_star(self, canvas, cx, cy, radius):
        self.circle_button(canvas, cx, cy, radius)
        draw = ImageDraw.Draw(canvas, "RGBA")
        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius_now = radius * (0.60 if i % 2 == 0 else 0.25)
            points.append(
                (
                    cx + radius_now * math.cos(angle),
                    cy + radius_now * math.sin(angle),
                )
            )
        draw.polygon(points, fill=COL_WHITE)

    def draw_dots(self, canvas, cx, cy, radius):
        self.circle_button(canvas, cx, cy, radius)
        draw = ImageDraw.Draw(canvas, "RGBA")
        dot = max(2, S(3))
        for offset in (-radius * 0.34, 0, radius * 0.34):
            draw.ellipse(
                (cx - dot, cy + offset - dot, cx + dot, cy + offset + dot),
                fill=COL_WHITE,
            )

    def draw_seekbar(self, canvas, fraction):
        draw = ImageDraw.Draw(canvas, "RGBA")
        x0, x1 = self.right_x, self.right_end
        y = self.seek_y
        fraction = max(0.0, min(1.0, float(fraction)))
        knob_x = x0 + (x1 - x0) * fraction
        thickness = S(9)

        draw.rounded_rectangle(
            (x0, y - thickness / 2, x1, y + thickness / 2),
            radius=thickness // 2,
            fill=(255, 255, 255, 235),
        )
        r = self.seek_thumb_r
        draw.ellipse(
            (knob_x - r, y - r, knob_x + r, y + r),
            fill=(255, 255, 255, 255),
        )

    def draw_time_row(self, canvas, elapsed, remaining, bot_name, avatar):
        draw = ImageDraw.Draw(canvas, "RGBA")
        y = self.time_y

        if elapsed:
            draw.text(
                (self.right_x, y),
                elapsed,
                font=self.font_time,
                fill=COL_SUBTITLE,
                anchor="lm",
            )

        if remaining:
            draw.text(
                (self.right_end, y),
                remaining,
                font=self.font_time,
                fill=COL_SUBTITLE,
                anchor="rm",
            )

        label = self.truncate(bot_name or "Music Bot", 20)
        has_avatar = avatar is not None
        avatar_size = self.pill_h - S(10) if has_avatar else 0
        gap = S(8) if has_avatar else 0
        padding = S(16)

        font = self.font_pill
        bbox = draw.textbbox((0, 0), label, font=font)
        text_width = bbox[2] - bbox[0]
        max_width = S(250)
        budget = max_width - padding * 2 - avatar_size - gap

        while text_width > budget and len(label) > 5:
            label = label[:-4].rstrip() + "..."
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]

        pill_width = padding * 2 + avatar_size + gap + text_width
        x0 = self.pill_cx - pill_width / 2
        x1 = self.pill_cx + pill_width / 2
        y0 = y - self.pill_h / 2
        y1 = y + self.pill_h / 2

        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=self.pill_h // 2,
            fill=(20, 20, 20, 210),
            outline=(255, 255, 255, 180),
            width=max(1, S(1)),
        )

        cursor = x0 + padding
        if has_avatar:
            av = self.fit_image(avatar, (int(avatar_size), int(avatar_size)))
            av = self.round_image(av, avatar_size // 2)
            canvas.alpha_composite(
                av, (int(cursor), int(y - avatar_size / 2))
            )
            av.close()
            cursor += avatar_size + gap

        draw.text(
            (cursor, y),
            label,
            font=font,
            fill=COL_WHITE,
            anchor="lm",
        )

    def draw_controls(self, canvas):
        draw = ImageDraw.Draw(canvas, "RGBA")
        y = self.controls_y

        # Previous
        tri_w, tri_h = S(28), S(42)
        gap = S(7)
        for cx, direction in (
            (self.rewind_x, -1),
            (self.forward_x, 1),
        ):
            for index in (0, 1):
                offset = (index - 0.5) * (tri_w + gap) * direction
                if direction == 1:
                    points = [
                        (cx + offset - tri_w / 2, y - tri_h / 2),
                        (cx + offset - tri_w / 2, y + tri_h / 2),
                        (cx + offset + tri_w / 2, y),
                    ]
                else:
                    points = [
                        (cx + offset + tri_w / 2, y - tri_h / 2),
                        (cx + offset + tri_w / 2, y + tri_h / 2),
                        (cx + offset - tri_w / 2, y),
                    ]
                draw.polygon(points, fill=COL_WHITE)

        # Pause
        bar_w = S(17)
        bar_h = S(65)
        gap = S(19)
        for cx in (
            self.play_cx - gap / 2 - bar_w / 2,
            self.play_cx + gap / 2 + bar_w / 2,
        ):
            draw.rounded_rectangle(
                (
                    cx - bar_w / 2,
                    y - bar_h / 2,
                    cx + bar_w / 2,
                    y + bar_h / 2,
                ),
                radius=max(2, bar_w // 3),
                fill=COL_WHITE,
            )

    def draw_speaker(self, draw, cx, y, waves=False):
        body_w, body_h = S(9), S(12)
        cone = S(11)

        draw.rectangle(
            (cx - body_w, y - body_h / 2, cx, y + body_h / 2),
            fill=COL_WHITE,
        )
        draw.polygon(
            [
                (cx, y - body_h / 2),
                (cx, y + body_h / 2),
                (cx + cone, y + body_h / 2 + cone * 0.6),
                (cx + cone, y - body_h / 2 - cone * 0.6),
            ],
            fill=COL_WHITE,
        )

        if waves:
            for radius in (S(10), S(16)):
                draw.arc(
                    (
                        cx + cone - radius,
                        y - radius,
                        cx + cone + radius,
                        y + radius,
                    ),
                    start=-40,
                    end=40,
                    fill=COL_WHITE,
                    width=max(1, S(2)),
                )

    def draw_volume(self, canvas):
        draw = ImageDraw.Draw(canvas, "RGBA")
        y = self.volume_y
        thickness = S(9)

        draw.rounded_rectangle(
            (self.vol_x0, y - thickness / 2, self.vol_x1, y + thickness / 2),
            radius=thickness // 2,
            fill=COL_WHITE,
        )

        self.draw_speaker(draw, self.vol_low_x, y, False)
        self.draw_speaker(draw, self.vol_high_x, y, True)

    def draw_bottom_icons(self, canvas):
        draw = ImageDraw.Draw(canvas, "RGBA")
        y = self.bottom_y

        cx = self.bottom_left_x
        width, height = S(34), S(24)
        draw.rounded_rectangle(
            (
                cx - width / 2,
                y - height / 2,
                cx + width / 2,
                y + height / 2,
            ),
            radius=S(6),
            outline=COL_MUTED,
            width=max(1, S(2)),
        )
        draw.polygon(
            [
                (cx - width * 0.18, y + height / 2),
                (cx - width * 0.02, y + height / 2),
                (cx - width * 0.14, y + height / 2 + S(8)),
            ],
            fill=COL_MUTED,
        )
        quote_font = _font(self.subtitle_font_path, S(13))
        draw.text(
            (cx, y - S(1)),
            '"',
            font=quote_font,
            fill=COL_MUTED,
            anchor="mm",
        )

        cx = self.bottom_right_x
        line_w = S(26)
        x0 = cx - line_w / 2 - S(6)
        for offset in (-S(9), 0, S(9)):
            dot = max(1, S(2))
            draw.ellipse(
                (x0 - dot, y + offset - dot, x0 + dot, y + offset + dot),
                fill=COL_MUTED,
            )
            draw.line(
                (x0 + S(8), y + offset, x0 + S(8) + line_w, y + offset),
                fill=COL_MUTED,
                width=max(1, S(2)),
            )

    def draw_panel(
        self,
        canvas,
        title,
        channel,
        bot_name,
        avatar=None,
        duration=None,
        elapsed=3,
    ):
        draw = ImageDraw.Draw(canvas, "RGBA")

        title_max = self.star_x - self.top_icon_r - self.right_x - S(24)
        title, title_font = self.fit_title(draw, title, title_max)

        draw.text(
            (self.right_x, self.title_y),
            title,
            font=title_font,
            fill=COL_WHITE,
        )
        draw.text(
            (self.right_x, self.subtitle_y),
            self.truncate(channel or "Unknown Artist", 34),
            font=self.font_subtitle,
            fill=COL_SUBTITLE,
        )

        self.draw_star(canvas, self.star_x, self.top_icon_y, self.top_icon_r)
        self.draw_dots(canvas, self.dots_x, self.top_icon_y, self.top_icon_r)

        duration = self.parse_duration(duration)
        try:
            elapsed_value = max(0.0, float(elapsed or 0))
        except (TypeError, ValueError):
            elapsed_value = 0.0

        fraction = 0.02
        remaining_text = None

        if duration and duration > 0:
            fraction = min(1.0, elapsed_value / duration)
            remaining = max(0.0, duration - elapsed_value)
            remaining_text = "-" + self.format_time(remaining)

        self.draw_seekbar(canvas, fraction)
        self.draw_time_row(
            canvas,
            self.format_time(elapsed_value),
            remaining_text,
            bot_name,
            avatar,
        )
        self.draw_controls(canvas)
        self.draw_volume(canvas)
        self.draw_bottom_icons(canvas)

    def apply_grain(self, canvas):
        w, h = canvas.size
        key = (w, h)
        if self._grain_cache_key != key:
            small_w = max(1, w // 4)
            small_h = max(1, h // 4)
            data = random.Random(11).randbytes(small_w * small_h)
            noise = Image.frombytes("L", (small_w, small_h), data)
            noise = noise.resize((w, h), Image.Resampling.BILINEAR)
            self._grain_alpha_cache = noise.point(
                lambda p: int(p * 7 / 255)
            )
            self._grain_cache_key = key

        layer = Image.new("RGBA", (w, h), (128, 128, 128, 0))
        layer.putalpha(self._grain_alpha_cache)
        canvas.alpha_composite(layer)
        layer.close()

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
        cover = cover_img.convert("RGB")
        accent = self.accent_from_cover(cover)

        canvas = self.build_background(cover)
        self.draw_card(canvas, cover, accent)
        self.draw_panel(
            canvas,
            title,
            channel_name,
            bot_name,
            avatar=avatar_img,
            duration=duration,
            elapsed=elapsed,
        )
        self.apply_grain(canvas)

        result = canvas.convert("RGB")
        canvas.close()
        cover.close()
        return result

    async def generate(self, media, output_path=None, user_avatar=None):
        cover_url = self.first_attr(
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
                "No thumbnail URL found on media object."
            )

        title = self.first_attr(
            media,
            "title",
            "name",
            default="Unknown Title",
        )
        channel_name = self.first_attr(
            media,
            "channel",
            "channel_name",
            "uploader",
            "artist",
            "user",
            default="Unknown Artist",
        )
        bot_name = self.first_attr(
            config,
            "BOT_NAME",
            "NAME",
            "APP_NAME",
            default="Music Bot",
        )
        duration = self.parse_duration(
            self.first_attr(
                media,
                "duration",
                "duration_seconds",
                "length",
                "track_duration",
                "seconds",
            )
        )

        avatar_source = user_avatar or self.first_attr(
            media,
            "user_photo",
            "user_photo_url",
            "user_avatar",
            "requester_photo",
            "played_by_photo",
            "user_pic",
            "user_dp",
        )

        if not output_path:
            media_id = self.first_attr(media, "id", default=uuid.uuid4().hex)
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"thumb_{media_id}.jpg",
            )

        output_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(output_dir, exist_ok=True)

        tmp_cover = output_path + ".cover.tmp"
        tmp_avatar = output_path + ".avatar.tmp"

        cover_img = None
        avatar_img = None
        final_img = None

        try:
            cover_task = asyncio.create_task(
                self.save_thumb(tmp_cover, str(cover_url))
            )

            if isinstance(avatar_source, Image.Image):
                avatar_img = avatar_source.convert("RGB")
            elif isinstance(avatar_source, str):
                if os.path.isfile(avatar_source):
                    avatar_img = await asyncio.to_thread(
                        self.load_image, avatar_source
                    )
                elif avatar_source.startswith(("http://", "https://")):
                    avatar_img = await self.fetch_avatar(
                        avatar_source,
                        tmp_avatar,
                    )

            await cover_task

            cover_img = await asyncio.to_thread(
                self.load_image,
                tmp_cover,
            )

            if cover_img is None:
                raise ValueError(
                    f"Unable to decode thumbnail image: {cover_url}"
                )

            final_img = await asyncio.to_thread(
                self.compose,
                cover_img,
                str(title),
                str(channel_name),
                str(bot_name),
                avatar_img,
                duration,
                3,
            )

            await asyncio.to_thread(
                final_img.save,
                output_path,
                "JPEG",
                quality=92,
                optimize=True,
            )

            return output_path

        except Exception as exc:
            print(f"[Thumbnail] generate failed: {exc}")
            raise

        finally:
            for image in (avatar_img, cover_img, final_img):
                try:
                    if image is not None:
                        image.close()
                except Exception:
                    pass

            for path in (tmp_cover, tmp_avatar):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
