# 4K Mobile Wallpaper Collection

A daily-updated collection of high-resolution wallpapers sourced from Wikimedia Commons.

## File naming and batches

Images are stored together in `wallpapers/` with sequential names:

```
wallpapers/
  image_1.jpg
  image_2.jpg
  image_3.jpg
  ...
  image_100.jpg
```

The first successful run downloads up to 100 images. Later runs continue at the next unused number (for example, `image_101.jpg`) and never intentionally overwrite an existing numbered file. The workflow is scheduled daily and can also be started manually from **Actions → Collect 4K wallpapers → Run workflow**.

## Copyright and reuse filter

The collector accepts only Wikimedia Commons files whose license metadata explicitly identifies **Public Domain** or **CC0**. It rejects Creative Commons Attribution (CC BY), ShareAlike, NonCommercial, NoDerivatives, and other licenses. This is a conservative filter, but automated metadata is not a legal guarantee: check the original file page before using an image commercially or redistributing it.

## Image quality and duplicate prevention

- Requires at least 3840 px on the long edge and 2160 px on the short edge.
- Validates image data and actual dimensions, converts accepted files to JPEG, and limits each output file to 15 MiB.
- Skips previously recorded source files and exact duplicate JPEG content.
- Saves source URL, creator metadata when supplied, license, dimensions, SHA-256, and download date in [manifest.json](manifest.json).
- Searches Nature, Space, Dark AMOLED, Cars, Abstract, Anime, Minimalist, Mountains, Ocean, and Architecture.

## Repository storage

The workflow has a 300 MiB wallpaper storage ceiling. A run may therefore download fewer than 100 images if the remaining space is insufficient. Git keeps old binary files in commit history, even if later deleted; for a large archive, use Git LFS or external object storage/CDN rather than storing thousands of full-resolution images in ordinary Git history.

## Run locally

```bash
python -m pip install -r requirements.txt
python scripts/collect_wallpapers.py
```

The repository automation code is separate from the images. Each image's source and reported license are recorded in `manifest.json`.
