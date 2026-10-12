"""Validate and preserve uploaded media; keep draft files outside the checkout."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import warnings
from pathlib import Path

from defusedxml import ElementTree
from PIL import Image, UnidentifiedImageError

from core import Session, UserError

EXTENSIONS = {
    "picture": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"},
    "background": {".png", ".jpg", ".jpeg", ".gif", ".mp4"},
    "music": {".mp3"},
}
MAX_BYTES = {"picture": 10 * 1024 * 1024, "background": 25 * 1024 * 1024, "music": 25 * 1024 * 1024}
FORMAT_NAMES = {".png":"PNG", ".jpg":"JPEG", ".jpeg":"JPEG", ".webp":"WEBP", ".gif":"GIF"}
SVG_TAGS = {
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "title", "desc",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern", "filter", "feGaussianBlur", "feOffset", "feFlood",
    "feComposite", "feMerge", "feMergeNode", "feColorMatrix", "feBlend", "feComponentTransfer", "feFuncR", "feFuncG", "feFuncB", "feFuncA",
    "use", "symbol", "image", "style",
}


def check_attachment(kind: str, filename: str, size: int) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in EXTENSIONS[kind]:
        raise UserError("Please send one " + {"picture":"PNG, JPG, WEBP, GIF, or SVG image", "background":"PNG, JPG, GIF, or MP4 background", "music":"MP3 music file"}[kind] + ".")
    if not 0 < size <= MAX_BYTES[kind]:
        raise UserError(f"That file must be between 1 byte and {MAX_BYTES[kind] // (1024*1024)} MB.")
    return ".jpg" if extension == ".jpeg" else extension


def validate_svg(path: Path) -> None:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
        if "<?xml-stylesheet" in text.lower():
            raise ValueError("External stylesheet")
        root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        if root.tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
            raise ValueError("Not SVG")
        for element in root.iter():
            tag = element.tag
            if tag.startswith("{") and not tag.startswith("{http://www.w3.org/2000/svg}"):
                raise ValueError("Foreign content")
            if tag.split("}")[-1] not in SVG_TAGS:
                raise ValueError("Active content")
            for key,value in element.attrib.items():
                local = key.split("}")[-1].lower()
                if local.startswith("on") or "javascript:" in value.lower() or "vbscript:" in value.lower():
                    raise ValueError("Active attribute")
                if local in ("href", "src") and not value.startswith("#"):
                    match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=\s]+)", value, re.I)
                    if not match:
                        raise ValueError("External reference")
                    import io
                    with Image.open(io.BytesIO(base64.b64decode(match[2], validate=False))) as embedded:
                        if embedded.format not in FORMAT_NAMES.values():
                            raise ValueError("Invalid embedded image")
                        embedded.verify()
            css = " ".join(element.attrib.values()) + (element.text or "" if tag.split("}")[-1] == "style" else "")
            urls = re.findall(r"url\s*\(([^)]*)\)", css, re.I)
            if "\\" in css or "@import" in css.lower() or any(not re.fullmatch(r"#[A-Za-z0-9_.:-]+", url.strip().strip("'\"")) for url in urls) or "{http://www.w3.org/XML/1998/namespace}base" in element.attrib:
                raise ValueError("External style reference")
    except Exception:
        raise UserError("Please send a valid static SVG without scripts or external links, or use a PNG, JPG, WEBP, or GIF.") from None


def validate_media(path: Path, kind: str, extension: str) -> None:
    if extension == ".svg":
        validate_svg(path)
        return
    if extension in FORMAT_NAMES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as picture:
                    if picture.format != FORMAT_NAMES[extension]:
                        raise ValueError("Wrong image format")
                    picture.verify()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise UserError("That image couldn't be read as the selected file type. Please send a valid image.") from None
        return
    with path.open("rb") as file:
        header = file.read(12)
    if extension == ".mp4" and header[4:8] != b"ftyp":
        raise UserError("That file isn't a valid MP4 video. Please send another MP4.")
    if extension == ".mp3" and not (header.startswith(b"ID3") or (len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)):
        raise UserError("That file isn't a valid MP3. Please send another MP3.")
    probe = shutil.which("ffprobe")
    if not probe:
        raise UserError("The upload checker is unavailable. Please ask the site owner to check the bot.")
    try:
        result = subprocess.run([probe,"-v","error","-protocol_whitelist","file,crypto,data","-probesize","8000000","-analyzeduration","5000000","-show_entries","format=format_name:stream=codec_type,codec_name","-of","json",str(path)], capture_output=True, timeout=15, check=True, env={"PATH":os.environ.get("PATH", os.defpath),"LC_ALL":"C"})
        info = json.loads(result.stdout)
        formats = set(info.get("format", {}).get("format_name", "").split(","))
        streams = info.get("streams", [])
        valid = "mp4" in formats and any(s.get("codec_type") == "video" for s in streams) if extension == ".mp4" else "mp3" in formats and any(s.get("codec_name") == "mp3" for s in streams)
        if not valid:
            raise ValueError("Wrong media format")
    except (subprocess.SubprocessError, OSError, ValueError):
        raise UserError("That " + ("MP4 video" if extension == ".mp4" else "MP3 music file") + " couldn't be read. Please send another file.") from None


def upload_path(root: Path, session_id: int, relative: str) -> Path:
    directory = (root / "uploads" / str(session_id)).resolve()
    candidate = (root / relative).resolve()
    if candidate.parent != directory:
        raise UserError("The saved upload is unavailable. Please upload it again.")
    return candidate


def clean_uploads(root: Path, session: Session) -> None:
    for entry in session.media.values():
        if entry:
            upload_path(root, session.id, entry["path"]).unlink(missing_ok=True)
    directory = root / "uploads" / str(session.id)
    if directory.exists():
        if directory.resolve().parent != (root / "uploads").resolve() or directory.resolve().name != str(session.id):
            raise UserError("The saved upload directory is unavailable.")
        for path in directory.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}\.(part|png|jpg|webp|gif|svg|mp4|mp3)", path.name) and path.is_file():
                path.unlink()
        if not any(directory.iterdir()):
            directory.rmdir()
