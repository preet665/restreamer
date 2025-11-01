import logging
from typing import Any, Dict, Iterable, Optional, Tuple

import yt_dlp
from yt_dlp.utils import DownloadError

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def home(request):
    """Render the main streaming page."""
    return render(request, "streams/index.html")


@require_GET
def stream_info(request):
    youtube_url = request.GET.get("url")
    if not youtube_url:
        return JsonResponse({"error": "Missing url parameter."}, status=400)

    logger.info("yt-dlp stream info requested url=%s", youtube_url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "skip_download": True,
    }

    try:
        info_dict = _extract_info(youtube_url, ydl_opts)
        qualities = _build_quality_options(info_dict)
        default_quality = _determine_default_quality(qualities)
        logger.debug(
            "yt-dlp extracted %d quality options for url=%s",
            len([q for q in qualities if q != "best"]),
            youtube_url,
        )
        return JsonResponse(
            {
                "qualities": qualities,
                "default_quality": default_quality,
                "title": info_dict.get("title", ""),
                "duration": info_dict.get("duration", 0),
                "thumbnail": info_dict.get("thumbnail", ""),
            }
        )
    except DownloadError as exc:
        logger.warning("yt-dlp download error for url=%s: %s", youtube_url, exc)
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected yt-dlp failure for url=%s", youtube_url)
        return JsonResponse({"error": str(exc)}, status=502)


@require_GET
def get_stream_url(request):
    youtube_url = request.GET.get("url")
    quality = request.GET.get("quality", "best")
    if not youtube_url:
        return JsonResponse({"error": "Missing url parameter."}, status=400)

    format_string = _format_string_for_quality(quality)
    logger.info(
        "yt-dlp stream URL requested url=%s quality=%s format=%s",
        youtube_url,
        quality,
        format_string,
    )

    ydl_opts = {
        "format": format_string,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }

    try:
        info_dict = _extract_info(youtube_url, ydl_opts)
        stream_url, stream_meta = _resolve_stream(info_dict)
        response = {
            "stream_url": stream_url,
            "title": info_dict.get("title", ""),
            "duration": info_dict.get("duration", 0),
            "quality": quality,
            "format_id": stream_meta.get("format_id"),
            "ext": stream_meta.get("ext"),
            "protocol": stream_meta.get("protocol"),
        }
        logger.debug(
            "yt-dlp resolved stream format_id=%s protocol=%s ext=%s",
            response["format_id"],
            response["protocol"],
            response["ext"],
        )
        return JsonResponse(response)
    except DownloadError as exc:
        logger.warning(
            "yt-dlp download error for url=%s quality=%s: %s",
            youtube_url,
            quality,
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected yt-dlp failure resolving stream for url=%s", youtube_url)
        return JsonResponse({"error": str(exc)}, status=502)


def _extract_info(youtube_url: str, options: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("Invoking yt-dlp for url=%s with options=%s", youtube_url, options)
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(youtube_url, download=False)


def _build_quality_options(info_dict: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    formats = info_dict.get("formats") or []
    quality_map: Dict[str, Dict[str, Any]] = {}

    for fmt in formats:
        height = fmt.get("height")
        if not height or fmt.get("vcodec") == "none":
            continue

        label = f"{int(height)}p"
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
        tbr = fmt.get("tbr") or 0
        candidate = {
            "format_id": fmt.get("format_id"),
            "ext": fmt.get("ext", "mp4"),
            "filesize": filesize,
            "fps": fmt.get("fps"),
            "tbr": tbr,
        }

        existing = quality_map.get(label)
        if existing is None or (existing.get("tbr") or 0) < tbr:
            quality_map[label] = candidate

    quality_map["best"] = {
        "format_id": "best",
        "ext": info_dict.get("ext", "mp4"),
        "filesize": info_dict.get("filesize") or info_dict.get("filesize_approx"),
        "fps": info_dict.get("fps"),
        "tbr": info_dict.get("tbr"),
    }

    return quality_map


def _determine_default_quality(options: Dict[str, Dict[str, Any]]) -> str:
    if "best" in options:
        return "best"

    numeric_labels = [
        label for label in options.keys() if label.endswith("p") and label[:-1].isdigit()
    ]
    if numeric_labels:
        return max(numeric_labels, key=lambda value: int(value[:-1]))

    return next(iter(options.keys()), "best")


def _format_string_for_quality(quality: str) -> str:
    height = _parse_height(quality)
    if height is None:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    return (
        "bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/"
        "best[ext=mp4][height<={height}]/"
        "best[height<={height}]"
    ).format(height=height)


def _parse_height(label: str) -> Optional[int]:
    if not label or label == "best":
        return None

    if label.endswith("p") and label[:-1].isdigit():
        return int(label[:-1])

    if label.isdigit():
        return int(label)

    return None


def _resolve_stream(info_dict: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    if info_dict.get("url"):
        return info_dict["url"], {
            "format_id": info_dict.get("format_id", "best"),
            "ext": info_dict.get("ext"),
            "protocol": info_dict.get("protocol"),
        }

    requested_formats = info_dict.get("requested_formats") or []
    if requested_formats:
        primary = requested_formats[0]
        url = primary.get("url")
        if url:
            return url, primary

    for fmt in _iter_formats(info_dict):
        if fmt.get("url"):
            return fmt["url"], fmt

    raise RuntimeError("No playable stream URL found.")


def _iter_formats(info_dict: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    formats = info_dict.get("formats") or []
    sorted_formats = sorted(
        formats,
        key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0),
        reverse=True,
    )
    for fmt in sorted_formats:
        yield fmt
