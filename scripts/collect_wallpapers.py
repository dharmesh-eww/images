#!/usr/bin/env python3
"""Download sequentially numbered 4K Public Domain / CC0 wallpapers."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

API_URL = "https://commons.wikimedia.org/w/api.php"
ROOT = Path(__file__).resolve().parents[1]
WALLPAPER_DIR = ROOT / "wallpapers"
MANIFEST_PATH = ROOT / "manifest.json"
USER_AGENT = "GitHubWallpaperCollector/2.0 (Public Domain and CC0 wallpaper archive)"
MIN_LONG_EDGE = int(os.getenv("MIN_LONG_EDGE", "3840"))
MIN_SHORT_EDGE = int(os.getenv("MIN_SHORT_EDGE", "2160"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(15 * 1024 * 1024)))
MAX_REPO_IMAGE_BYTES = int(os.getenv("MAX_REPO_IMAGE_BYTES", str(300 * 1024 * 1024)))
MAX_NEW_PER_RUN = int(os.getenv("MAX_NEW_PER_RUN", "100"))
PER_CATEGORY = int(os.getenv("PER_CATEGORY", "10"))
DELAY_SECONDS = 0.5

CATEGORIES = {
    "nature": "nature landscape",
    "space": "nebula galaxy planet",
    "dark-amoled": "dark abstract black background",
    "cars": "sports car automobile",
    "abstract": "abstract digital art",
    "anime": "anime illustration",
    "minimalist": "minimalist wallpaper",
    "mountains": "mountain landscape",
    "ocean": "ocean sea waves",
    "architecture": "modern architecture",
}
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def current_image_bytes() -> int:
    return sum(p.stat().st_size for p in WALLPAPER_DIR.glob("image_*.jpg") if p.is_file())


def next_image_number() -> int:
    numbers = []
    for path in WALLPAPER_DIR.glob("image_*.jpg"):
        match = re.fullmatch(r"image_(\d+)\.jpg", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def clean_metadata(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def license_info(info: dict) -> tuple[str, str, str] | None:
    """Allow only explicit Public Domain or CC0 labels; reject all other licenses."""
    ext = info.get("extmetadata", {})
    short = clean_metadata(ext.get("LicenseShortName", {}).get("value", ""))
    terms = clean_metadata(ext.get("UsageTerms", {}).get("value", ""))
    author = clean_metadata(ext.get("Artist", {}).get("value", ""))
    combined = (short + " " + terms).casefold()

    if re.search(r"\bcc0\b", combined):
        return short or "CC0", author, terms
    if "public domain" in combined:
        # Exclude CC BY/SA/NC/ND labels even if a metadata field also mentions
        # public-domain material in a description.
        if any(token in combined for token in ("creative commons", "cc-by", "cc by", "noncommercial", "non-commercial", "no derivatives")):
            return None
        return short or "Public Domain", author, terms
    return None


def search_candidates(term: str) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{term} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 50,
        "gsrsort": "relevance",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    response = session.get(API_URL, params=params, timeout=30)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    return list(pages.values())


def download_candidate(
    page: dict,
    category: str,
    known_ids: set[str],
    known_hashes: set[str],
    manifest: list[dict],
    number: int,
) -> bool:
    page_id = str(page.get("pageid", ""))
    if not page_id or page_id in known_ids:
        return False
    infos = page.get("imageinfo", [])
    if not infos:
        return False
    info = infos[0]
    width, height = int(info.get("width", 0)), int(info.get("height", 0))
    if min(width, height) < MIN_SHORT_EDGE or max(width, height) < MIN_LONG_EDGE:
        return False
    if info.get("size", MAX_FILE_BYTES + 1) > MAX_FILE_BYTES:
        return False
    lic = license_info(info)
    if not lic:
        return False
    license_name, author, usage_terms = lic
    original_url = info.get("url", "")
    if not original_url or not info.get("mime", "").startswith("image/"):
        return False

    target = WALLPAPER_DIR / f"image_{number}.jpg"
    if target.exists():
        return False

    try:
        response = session.get(original_url, timeout=(20, 90))
        response.raise_for_status()
        if len(response.content) > MAX_FILE_BYTES:
            return False
        with Image.open(BytesIO(response.content)) as source:
            source.verify()
        with Image.open(BytesIO(response.content)) as source:
            image = ImageOps.exif_transpose(source)
            actual_width, actual_height = image.size
            if min(actual_width, actual_height) < MIN_SHORT_EDGE or max(actual_width, actual_height) < MIN_LONG_EDGE:
                return False
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "black")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.save(target, format="JPEG", quality=92, optimize=True, progressive=True)
        output_bytes = target.stat().st_size
        if output_bytes > MAX_FILE_BYTES:
            target.unlink(missing_ok=True)
            return False
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest in known_hashes:
            target.unlink(missing_ok=True)
            known_ids.add(page_id)
            print(f"Skipped duplicate image content: {page.get('title')}")
            return False
        if current_image_bytes() > MAX_REPO_IMAGE_BYTES:
            target.unlink(missing_ok=True)
            print(f"Storage cap reached ({MAX_REPO_IMAGE_BYTES} bytes); stopping collection.")
            raise RuntimeError("REPOSITORY_STORAGE_CAP")
    except RuntimeError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        print(f"Skipped {page.get('title')}: {exc}")
        return False

    extmeta = info.get("extmetadata", {})
    description = clean_metadata(extmeta.get("ImageDescription", {}).get("value", ""))
    manifest.append({
        "file": str(target.relative_to(ROOT)),
        "category": category,
        "commons_title": page.get("title", ""),
        "commons_page_url": info.get("descriptionurl", ""),
        "original_url": original_url,
        "author": author,
        "license": license_name,
        "license_terms": usage_terms,
        "description": description,
        "width": actual_width,
        "height": actual_height,
        "sha256": digest,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    })
    known_ids.add(page_id)
    known_hashes.add(digest)
    print(f"Added {target.relative_to(ROOT)} ({actual_width}x{actual_height}; {license_name})")
    return True


def main() -> None:
    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    known_ids = set()
    for item in manifest:
        url = item.get("commons_page_url", "")
        match = re.search(r"[?&]curid=(\d+)", url)
        if match:
            known_ids.add(match.group(1))
    known_hashes = {
        item.get("sha256") for item in manifest if item.get("sha256")
    }
    # Also recognize numbered files already present, including files not in manifest.
    for path in WALLPAPER_DIR.glob("image_*.jpg"):
        if path.is_file():
            try:
                known_hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
            except OSError:
                pass

    number = next_image_number()
    added = 0
    stop = False
    for category, query in CATEGORIES.items():
        if added >= MAX_NEW_PER_RUN or stop:
            break
        try:
            candidates = search_candidates(query)
        except Exception as exc:
            print(f"Search failed for {category}: {exc}")
            continue
        category_added = 0
        for page in candidates:
            if added >= MAX_NEW_PER_RUN or category_added >= PER_CATEGORY:
                break
            try:
                success = download_candidate(
                    page, category, known_ids, known_hashes, manifest, number
                )
                if success:
                    added += 1
                    category_added += 1
                    number += 1
            except RuntimeError as exc:
                if str(exc) == "REPOSITORY_STORAGE_CAP":
                    stop = True
                    break
                raise
            time.sleep(DELAY_SECONDS)

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Finished: added {added} wallpaper(s); next image number is {number}.")
    print(f"Manifest contains {len(manifest)} entries.")


if __name__ == "__main__":
    main()
