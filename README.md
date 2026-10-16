# 4K Mobile Wallpaper Collection

A daily-updated collection of high-resolution wallpapers sourced from Wikimedia Commons.

## Categories

Nature, Space, Dark AMOLED, Cars, Abstract, Anime, Minimalist, Mountains, Ocean, and Architecture.

## Automation

GitHub Actions runs daily and can also be started manually from **Actions → Collect 4K wallpapers → Run workflow**. The collector:

- Searches Wikimedia Commons, not arbitrary websites.
- Accepts only files whose metadata indicates Public Domain, CC0, CC BY, or CC BY-SA licensing; excludes non-commercial and no-derivatives licenses.
- Requires both dimensions to be at least 2160 px and the long edge to be at least 3840 px.
- Verifies actual image dimensions and file integrity, limits each file to 15 MiB, and skips known Commons file IDs.
- Adds up to 10 images per run, at most one per category.
- Records source page, creator, license, dimensions, and SHA-256 in [manifest.json](manifest.json).

A category may receive no image on a given day if no candidate passes all checks. Licensing metadata should always be reviewed before reuse; the manifest provides source links and attribution details.

## Repository storage

The workflow stops adding files once the current wallpaper directory exceeds 300 MiB. This is a safety ceiling, not a GitHub quota. Git stores every committed version of binary files, so deleting a wallpaper later does not remove its historical copy. For a large or long-lived collection, use Git LFS or external object storage/CDN instead of keeping all original images in Git history.

GitHub Actions requires write access to repository contents. Scheduled workflows can be delayed during high load and may not run in a disabled/inactive repository.

## Run locally

```bash
python -m pip install -r requirements.txt
python scripts/collect_wallpapers.py
```

## License and attribution

This repository's automation code is separate from the wallpapers. Each image retains the license and attribution information recorded in `manifest.json`; follow the license terms on the original Commons file page. Do not assume all images share one license.
