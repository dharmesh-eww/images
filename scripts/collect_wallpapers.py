#!/usr/bin/env python3
"""Collect high-resolution, openly licensed wallpapers from Wikimedia Commons.

Only saves files whose Commons metadata identifies a permissive license (CC0,
Public Domain, CC BY, or CC BY-SA), and records attribution/source metadata.
No API key is required. Respect Wikimedia Commons API policies and rate limits.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PIL import Image

API_URL = "https://commons.wikimedia.org/w/api.php"
ROOT = Path(__file__).resolve().parents[1]
WALLPAPER_DIR = ROOT / "wallpapers"
MANIFEST_PATH = ROOT / "manifest.json"
USER_AGENT = "GitHubWallpaperCollector/1.0 (personal open-license wallpaper archive)"
MIN_LONG_EDGE = int(os.getenv("MIN_LONG_EDGE", "3840"))
MIN_SHORT_EDGE = int(os.getenv("MIN_SHORT_EDGE", "2160"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(15 * 1024 * 1024)))
MAX_REPO_IMAGE_BYTES = int(os.getenv("MAX_REPO_IMAGE_BYTES", str(300 * 1024 * 1024)))
MAX_NEW_PER_RUN = int(os.getenv("MAX_NEW_PER_RUN", "10"))
PER_CATEGORY = int(os.getenv("PER_CATEGORY", "1"))
DELAY_SECONDS = 1.0

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
    return sum(p.stat().st_size for p in WALLPAPER_DIR.rglob("*") if p.is_file())


def license_info(metadata: dict) -> tuple[str, str, str] | None:
    ext = metadata.get("extmetadata", {})
    short = re.sub(r"<[^>]+>", "", ext.get("LicenseShortName", {}).get("value", "")).strip()
    terms = re.sub(r"<[^>]+>", "", ext.get("UsageTerms", {}).get("value", "")).strip()
    author = re.sub(r"<[^>]+>", "", ext.get("Artist", {}).get("value", "")).strip()
    combined = (short + " " + terms).lower()

    # Allow only licenses with clear redistribution rights and attribution terms.
    if "public domain" in combined or re.search(r"\bcc0\b", combined):
        return short or terms or "Public Domain", author, terms
    if ("creative commons" in combined or re.search(r"\bcc by\b", combined)) and (
        re.search(r"\bcc by(?:-sa)?\s*(?:1\.|2\.|3\.|4\.|\()", combined)
        or re.search(r"\bcc by(?:-sa)?\b", combined)
    ):
        if any(term in combined for term in ("-nc", " noncommercial", "non-commercial", "-nd", "no derivatives")):
            return None
        if "cc by" in combined or "cc-by" in combined:
            return short or terms, author, terms
    return None


def search_candidates(term: str) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{term} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 50,
        "gsrsort": "timestamp",
        "gsrsortorder": "desc",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    response = session.get(API_URL, params=params, timeout=30)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    return list(pages.values())


def safe_slug(value: str) -> str:
    value = unquote(value)
    value = re.sub(r"\.[^.]+$", "", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:80] or "wallpaper"


def get_extension(url: str, mime: str) -> str | None:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return ".jpg" if ext == ".jpeg" else ext
    return { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" }.get(mime)


def download_candidate(page: dict, category: str, known_ids: set[str], manifest: list[dict]) -> bool:
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
    mime = info.get("mime", "")
    ext = get_extension(original_url, mime)
    if not ext or not original_url:
        return False

    # Wikimedia file pages have stable page IDs, preventing duplicate downloads.
    filename = f"{category}-{page_id}-{safe_slug(page.get('title', 'wallpaper'))}{ext}"
    target = WALLPAPER_DIR / category / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        known_ids.add(page_id)
        return False

    try:
        with session.get(original_url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            downloaded = 0
            with target.open("wb") as out:
                for chunk in response.iter_content(1024 * 128):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_BYTES:
                        raise ValueError("Download exceeded MAX_FILE_BYTES")
                    digest.update(chunk)
                    out.write(chunk)
        with Image.open(target) as image:
            image.verify()
        with Image.open(target) as image:
            actual_width, actual_height = image.size
        if min(actual_width, actual_height) < MIN_SHORT_EDGE or max(actual_width, actual_height) < MIN_LONG_EDGE:
            target.unlink(missing_ok=True)
            return False
        if current_image_bytes() > MAX_REPO_IMAGE_BYTES:
            target.unlink(missing_ok=True)
            print(f"Storage cap reached ({MAX_REPO_IMAGE_BYTES} bytes); stopping additions.")
            raise RuntimeError("REPOSITORY_STORAGE_CAP")
    except Exception as exc:
        target.unlink(missing_ok=True)
        if str(exc) == "REPOSITORY_STORAGE_CAP":
            raise
        print(f"Skipped {page.get('title')}: {exc}")
        return False

    extmeta = info.get("extmetadata", {})
    description = re.sub(r"<[^>]+>", "", extmeta.get("ImageDescription", {}).get("value", "")).strip()
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
        "sha256": digest.hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    })
    known_ids.add(page_id)
    print(f"Added {target.relative_to(ROOT)} ({actual_width}x{actual_height}, {license_name})")
    return True


def main() -> None:
    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    known_ids = {
        str(item.get("commons_page_url", "")).split("pageid=")[-1]
        for item in manifest if item.get("commons_page_url")
    }
    # More reliable duplicate key: parse page ID from existing filenames too.
    for path in WALLPAPER_DIR.rglob("*"):
        if path.is_file():
            match = re.search(r"-(\d+)-", path.name)
            if match:
                known_ids.add(match.group(1))

    added = 0
    for category, query in CATEGORIES.items():
        if added >= MAX_NEW_PER_RUN:
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
                if download_candidate(page, category, known_ids, manifest):
                    added += 1
                    category_added += 1
            except RuntimeError as exc:
                if str(exc) == "REPOSITORY_STORAGE_CAP":
                    break
                raise
            time.sleep(DELAY_SECONDS)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Finished: added {added} wallpaper(s); manifest has {len(manifest)} entries.")


if __name__ == "__main__":
    main()
