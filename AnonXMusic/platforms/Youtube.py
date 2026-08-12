import asyncio
import glob
import os
import random
import re
from typing import Union
from urllib.parse import parse_qs, urlparse

import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ytSearch import VideosSearch, Playlist
from AnonXMusic import LOGGER
from AnonXMusic.utils.formatters import time_to_seconds
from config import WORKER_FALLBACK_API_KEY, WORKER_FALLBACK_API_URL

logger = LOGGER(__name__)

def cookie_txt_file():
    try:
        folder_path = f"{os.getcwd()}/cookies"
        filename = f"{os.getcwd()}/cookies/logs.csv"
        txt_files = glob.glob(os.path.join(folder_path, '*.txt'))
        if not txt_files:
            raise FileNotFoundError("No .txt files found in the specified folder.")
        cookie_txt_file = random.choice(txt_files)
        with open(filename, 'a') as file:
            file.write(f'Choosen File : {cookie_txt_file}\n')
        return f"""cookies/{str(cookie_txt_file).split("/")[-1]}"""
    except:
        return None


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self.dl_stats = {
            "total_requests": 0,
            "worker_downloads": 0,
            "cookie_downloads": 0,
            "existing_files": 0
        }

    def _normalize_link(self, link: str):
        if not link:
            return link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        return link

    def _extract_video_id(self, link: str):
        if not link:
            return None
        link = self._normalize_link(str(link).strip())
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", link):
            return link
        parsed = urlparse(link)
        query_video_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_video_id:
            return query_video_id
        if parsed.netloc.endswith("youtu.be"):
            return parsed.path.strip("/").split("/")[0] or None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
        return None

    def _build_browser_headers(self):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.youtube.com/",
        }

    def _create_session(self):
        session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _extract_error_message(self, payload, fallback="Unknown error"):
        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return fallback

    def _extract_download_url(self, payload):
        def walk(value):
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            if isinstance(value, dict):
                for key in (
                    "audio_url",
                    "audioUrl",
                    "video_url",
                    "videoUrl",
                    "directLink",
                    "directUrl",
                    "direct_url",
                    "streamLink",
                    "streamUrl",
                    "stream_url",
                    "streamingUrl",
                    "streaming_url",
                    "playbackUrl",
                    "playback_url",
                    "downloads",
                    "downloadUrl",
                    "download_url",
                    "download",
                    "link",
                ):
                    found = walk(value.get(key))
                    if found:
                        return found
            if isinstance(value, list):
                for item in value:
                    found = walk(item)
                    if found:
                        return found
            return None

        return walk(payload)

    def _fetch_worker_media_link_sync(self, vid_id, media_format):
        if not WORKER_FALLBACK_API_URL or not WORKER_FALLBACK_API_KEY:
            logger.error("Worker API URL/key not configured.")
            return None

        api_url = f"{WORKER_FALLBACK_API_URL.rstrip('/')}/api"
        payload = {
            "key": WORKER_FALLBACK_API_KEY,
            "url": f"{self.base}{vid_id}",
            "format": media_format,
        }
        session = None
        try:
            session = self._create_session()
            attempts = (
                ("GET", lambda: session.get(api_url, params=payload, timeout=75)),
                (
                    "POST",
                    lambda: session.post(
                        api_url,
                        json=payload,
                        headers={"Content-Type": "application/json", **self._build_browser_headers()},
                        timeout=75,
                    ),
                ),
            )
            for method_name, request in attempts:
                response = request()
                try:
                    data = response.json()
                except ValueError:
                    data = None

                media_url = self._extract_download_url(data)
                if response.ok and media_url:
                    return media_url

                message = self._extract_error_message(
                    data,
                    response.text[:250] if response.text else f"HTTP {response.status_code}",
                )
                logger.error(
                    f"Worker API {method_name} {media_format} lookup failed for {vid_id}: {message}"
                )
                code = data.get("code") if isinstance(data, dict) else None
                if response.status_code == 401 or code in {
                    "authentication_required",
                    "invalid_key",
                    "invalid_api_key",
                }:
                    break
        except requests.RequestException as exc:
            logger.error(f"Worker API request failed for {vid_id}: {exc}")
        finally:
            if session:
                session.close()
        return None

    def _safe_filename(self, value: str):
        if not value:
            return value
        cleaned = value.replace("/", "_").replace("\\", "_")
        while ".." in cleaned:
            cleaned = cleaned.replace("..", ".")
        return cleaned

    def _apply_cookiefile_option(self, options: dict):
        cookie_file = cookie_txt_file()
        if cookie_file:
            options["cookiefile"] = cookie_file
        return options


    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]


        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            f"{link}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        playlist = await Playlist.get(link)
        if playlist:
            videos = []
            for video in playlist["videos"][:limit]:
                try:
                    duration = video.get("duration")
                    if duration:
                        duration_sec = int(time_to_seconds(duration))
                    else:
                        duration_sec = 0
                    videos.append({
                        "vidid": video["id"],
                        "title": video.get("title", "Unknown"),
                        "duration_min": duration,
                        "duration_sec": duration_sec,
                        "thumbnail": video.get("thumbnails", [{}])[0].get("url", "").split("?")[0] if video.get("thumbnails") else "",
                    })
                except:
                    continue
            return videos
        return None

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        try:
            results = []
            search = VideosSearch(link, limit=10)
            search_results = (await search.next()).get("result", [])

            # Filter videos longer than 1 hour
            for result in search_results:
                duration_str = result.get("duration", "0:00")
                try:
                    parts = duration_str.split(":")
                    duration_secs = 0
                    if len(parts) == 3:
                        duration_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration_secs = int(parts[0]) * 60 + int(parts[1])

                    if duration_secs <= 3600:
                        results.append(result)
                except (ValueError, IndexError):
                    continue

            if not results or query_type >= len(results):
                raise ValueError("No suitable videos found within duration limit")

            selected = results[query_type]
            return (
                selected["title"],
                selected["duration"],
                selected["thumbnails"][0]["url"].split("?")[0],
                selected["id"]
            )

        except Exception as e:
            LOGGER(__name__).error(f"Error in slider: {str(e)}")
            raise ValueError("Failed to fetch video details")

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        vid_id = link if videoid else self._extract_video_id(link)
        if videoid:
            link = self.base + link
        link = self._normalize_link(link)
        loop = asyncio.get_running_loop()
        os.makedirs("downloads", exist_ok=True)

        async def download_with_ytdlp(url, filepath, headers=None, max_retries=3):
            merged_headers = self._build_browser_headers()
            if headers:
                merged_headers.update(headers)

            def run_download():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "outtmpl": filepath,
                    "force_overwrites": True,
                    "nopart": True,
                    "retries": max_retries,
                    "http_headers": merged_headers,
                    "concurrent_fragment_downloads": 8,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                await loop.run_in_executor(None, run_download)
                if os.path.exists(filepath):
                    return filepath
            except Exception as e:
                logger.error(f"yt-dlp direct download failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None

        async def download_with_requests(url, filepath, headers=None):
            session = None
            try:
                session = self._create_session()
                request_headers = self._build_browser_headers()
                if headers:
                    request_headers.update(headers)

                response = session.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=60,
                    allow_redirects=True,
                )
                response.raise_for_status()
                chunk_size = 1024 * 1024

                with open(filepath, "wb") as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)

                return filepath

            except Exception as e:
                logger.error(f"Requests download failed: {str(e)}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return None
            finally:
                if session:
                    session.close()

        async def download_from_source(url, filepath, headers=None):
            result = await download_with_ytdlp(url, filepath, headers)
            if result:
                return result
            return await download_with_requests(url, filepath, headers)

        async def get_worker_media_link(current_vid_id, media_format):
            return await loop.run_in_executor(
                None,
                self._fetch_worker_media_link_sync,
                current_vid_id,
                media_format,
            )

        def download_from_youtube_sync(source_link, media_format, filepath):
            outtmpl = os.path.join("downloads", f"{vid_id}.%(ext)s")
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "force_overwrites": True,
                "noplaylist": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "outtmpl": outtmpl,
                "prefer_ffmpeg": True,
            }
            if media_format == "mp4":
                ydl_opts.update(
                    {
                        "format": (
                            "(bestvideo[height<=?720][width<=?1280][ext=mp4]/"
                            "best[height<=?720][width<=?1280])"
                            "+(bestaudio[ext=m4a]/bestaudio)/"
                            "best[height<=?720][width<=?1280]"
                        ),
                        "merge_output_format": "mp4",
                    }
                )
            else:
                ydl_opts.update(
                    {
                        "format": "bestaudio/best",
                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ],
                    }
                )
            self._apply_cookiefile_option(ydl_opts)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_link])
            return filepath if os.path.exists(filepath) else None

        async def download_from_youtube_fallback(source_link, media_format, filepath):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                return await loop.run_in_executor(
                    None,
                    download_from_youtube_sync,
                    source_link,
                    media_format,
                    filepath,
                )
            except Exception as exc:
                logger.error(f"yt-dlp fallback download failed for {vid_id}: {exc}")
                return None

        async def audio_dl(current_vid_id):
            filepath = os.path.join("downloads", f"{current_vid_id}.mp3")
            if os.path.exists(filepath):
                return filepath

            audio_url = await get_worker_media_link(current_vid_id, "mp3")
            if audio_url:
                result = await download_from_source(audio_url, filepath)
                if result:
                    return result

            logger.warning(
                f"Worker audio API failed for {current_vid_id}, trying yt-dlp fallback."
            )
            return await download_from_youtube_fallback(link, "mp3", filepath)

        async def video_dl(current_vid_id):
            filepath = os.path.join("downloads", f"{current_vid_id}.mp4")
            if os.path.exists(filepath):
                return filepath

            video_url = await get_worker_media_link(current_vid_id, "mp4")
            if video_url:
                result = await download_from_source(video_url, filepath)
                if result:
                    return result

            logger.warning(
                f"Worker video API failed for {current_vid_id}, trying yt-dlp fallback."
            )
            return await download_from_youtube_fallback(link, "mp4", filepath)

        def song_video_dl():
            safe_title = self._safe_filename(title)
            fpath = f"downloads/{safe_title}"
            ydl_opts = self._apply_cookiefile_option(
                {
                    "format": f"{format_id}+140",
                    "outtmpl": fpath,
                    "geo_bypass": True,
                    "nocheckcertificate": True,
                    "quiet": True,
                    "no_warnings": True,
                    "prefer_ffmpeg": True,
                    "merge_output_format": "mp4",
                }
            )
            yt_dlp.YoutubeDL(ydl_opts).download([link])

        def song_audio_dl():
            safe_title = self._safe_filename(title)
            fpath = f"downloads/{safe_title}.%(ext)s"
            ydl_opts = self._apply_cookiefile_option(
                {
                    "format": format_id,
                    "outtmpl": fpath,
                    "geo_bypass": True,
                    "nocheckcertificate": True,
                    "quiet": True,
                    "no_warnings": True,
                    "prefer_ffmpeg": True,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
            yt_dlp.YoutubeDL(ydl_opts).download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{self._safe_filename(title)}.mp4"
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{self._safe_filename(title)}.mp3"
            return fpath
        elif video:
            direct = True
            if not vid_id:
                raise RuntimeError("Video ID could not be resolved for video download.")
            downloaded_file = await video_dl(vid_id)
        else:
            direct = True
            if not vid_id:
                raise RuntimeError("Video ID could not be resolved for audio download.")
            downloaded_file = await audio_dl(vid_id)

        if not downloaded_file:
            media_type = "video" if video else "audio"
            raise RuntimeError(f"Failed to download {media_type} for {vid_id or link}.")
        return downloaded_file, direct
