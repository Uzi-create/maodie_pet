#!/usr/bin/env python3
"""Prepare the supplied round-headed Maodie media for the desktop pet.

This pipeline is deliberately mechanical: it only crops, masks, feathers and
encodes pixels from the user's source files.  It never redraws or synthesizes
the character.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "素材"
ASSET_DIR = ROOT / "assets"

SOURCES = {
    "idle": SOURCE_DIR / "屏幕截图 2026-08-30 173546.jpg",
    "crawl": SOURCE_DIR / "681f86b5ceb32HIA.gif",
    "hiss": SOURCE_DIR / "R.gif",
    "lick": SOURCE_DIR / "R (1).gif",
}


def _read_animation(path: Path) -> tuple[list[Image.Image], list[int]]:
    with Image.open(path) as image:
        frames: list[Image.Image] = []
        durations: list[int] = []
        fallback = int(image.info.get("duration", 80)) or 80
        for frame in ImageSequence.Iterator(image):
            frames.append(frame.convert("RGBA"))
            durations.append(int(frame.info.get("duration", fallback)) or fallback)
    return frames, durations


def _scaled_polygon(
    points: Sequence[tuple[float, float]], width: int, height: int
) -> np.ndarray:
    return np.asarray(
        [(round(x * width), round(y * height)) for x, y in points], np.int32
    )


def _ellipse(mask: np.ndarray, box: tuple[float, float, float, float], value: int) -> None:
    height, width = mask.shape
    x0, y0, x1, y1 = box
    center = (round((x0 + x1) * width / 2), round((y0 + y1) * height / 2))
    axes = (max(1, round((x1 - x0) * width / 2)), max(1, round((y1 - y0) * height / 2)))
    cv2.ellipse(mask, center, axes, 0, 0, 360, value, -1, cv2.LINE_AA)


def _keep_seeded_components(binary: np.ndarray, seed: np.ndarray) -> np.ndarray:
    count, labels = cv2.connectedComponents(binary.astype(np.uint8), connectivity=8)
    if count <= 1:
        return binary
    keep_labels = np.unique(labels[seed > 0])
    keep_labels = keep_labels[keep_labels != 0]
    if not len(keep_labels):
        sizes = np.bincount(labels.ravel())
        keep_labels = np.asarray([1 + int(np.argmax(sizes[1:]))])
    return np.isin(labels, keep_labels)


def _grabcut_alpha(
    rgba: Image.Image,
    probable_polygons: Sequence[Sequence[tuple[float, float]]],
    definite_ellipses: Sequence[tuple[float, float, float, float]],
    allowed_polygons: Sequence[Sequence[tuple[float, float]]] | None = None,
    iterations: int = 5,
    feather: float = 1.15,
) -> np.ndarray:
    rgb = np.asarray(rgba.convert("RGB"))
    height, width = rgb.shape[:2]
    gc_mask = np.full((height, width), cv2.GC_BGD, np.uint8)

    probable = np.zeros((height, width), np.uint8)
    for points in probable_polygons:
        cv2.fillPoly(probable, [_scaled_polygon(points, width, height)], 255)
    gc_mask[probable > 0] = cv2.GC_PR_FGD

    definite = np.zeros_like(probable)
    for box in definite_ellipses:
        _ellipse(definite, box, 255)
    gc_mask[definite > 0] = cv2.GC_FGD

    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        gc_mask,
        None,
        background_model,
        foreground_model,
        iterations,
        cv2.GC_INIT_WITH_MASK,
    )
    binary = np.isin(gc_mask, (cv2.GC_FGD, cv2.GC_PR_FGD))

    if allowed_polygons:
        allowed = np.zeros_like(probable)
        for points in allowed_polygons:
            cv2.fillPoly(allowed, [_scaled_polygon(points, width, height)], 255)
        binary &= allowed > 0

    binary = cv2.morphologyEx(
        binary.astype(np.uint8),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    ).astype(bool)
    binary = _keep_seeded_components(binary, definite)
    alpha = binary.astype(np.float32) * 255.0
    if feather > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), feather)
    alpha[alpha < 2] = 0
    alpha[alpha > 253] = 255
    return alpha.astype(np.uint8)


def _apply_alpha(frame: Image.Image, alpha: np.ndarray) -> Image.Image:
    output = frame.convert("RGBA")
    output.putalpha(Image.fromarray(alpha, "L"))
    return output


def _union_bbox(frames: Iterable[Image.Image], padding: int = 6) -> tuple[int, int, int, int]:
    frames = list(frames)
    width, height = frames[0].size
    boxes = [frame.getchannel("A").getbbox() for frame in frames]
    boxes = [box for box in boxes if box]
    if not boxes:
        return (0, 0, width, height)
    left = max(0, min(box[0] for box in boxes) - padding)
    top = max(0, min(box[1] for box in boxes) - padding)
    right = min(width, max(box[2] for box in boxes) + padding)
    bottom = min(height, max(box[3] for box in boxes) + padding)
    return left, top, right, bottom


def _crop_animation(frames: list[Image.Image], padding: int = 6) -> list[Image.Image]:
    box = _union_bbox(frames, padding)
    return [frame.crop(box) for frame in frames]


def _border_connected_white_alpha(frame: Image.Image) -> np.ndarray:
    """Remove only bright background connected to an image border.

    The spider legs contain white pixels too.  Connectivity is what prevents
    those enclosed white fills from being mistaken for the white canvas.
    """

    rgb = np.asarray(frame.convert("RGB"), dtype=np.int16)
    minimum = rgb.min(axis=2)
    maximum = rgb.max(axis=2)
    candidate = ((minimum >= 205) & ((maximum - minimum) <= 70)).astype(np.uint8)
    count, labels = cv2.connectedComponents(candidate, connectivity=8)
    border_labels = np.unique(
        np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))
    )
    border_labels = border_labels[border_labels != 0]
    background = np.isin(labels, border_labels).astype(np.uint8)

    # Fill the isolated single-pixel palette dither in the otherwise white field.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    background = cv2.morphologyEx(background, cv2.MORPH_CLOSE, kernel)
    # Never let the cleanup jump across the dark outline of the spider legs.
    dark_outline = (maximum < 145).astype(np.uint8)
    background[dark_outline > 0] = 0

    alpha = (1.0 - background.astype(np.float32)) * 255.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.55)
    alpha[alpha < 5] = 0
    alpha[alpha > 250] = 255
    return alpha.astype(np.uint8)


def _save_transparent_gif(
    frames: list[Image.Image], durations: list[int], destination: Path
) -> None:
    """Encode RGBA frames as GIF with a reserved transparent palette index."""

    prepared: list[Image.Image] = []
    for rgba in frames:
        alpha = np.asarray(rgba.getchannel("A"))
        # Reserve palette index 255 for transparency.  Quantize RGB to 255 colors.
        paletted = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        palette = paletted.getpalette()[: 255 * 3] + [0, 0, 0]
        paletted.putpalette(palette)
        indices = np.asarray(paletted).copy()
        indices[alpha < 128] = 255
        transparent = Image.fromarray(indices.astype(np.uint8), "P")
        transparent.putpalette(palette)
        transparent.info["transparency"] = 255
        transparent.info["disposal"] = 2
        prepared.append(transparent)

    prepared[0].save(
        destination,
        save_all=True,
        append_images=prepared[1:],
        duration=durations,
        loop=0,
        transparency=255,
        disposal=2,
        optimize=False,
    )


def prepare_idle() -> Path:
    with Image.open(SOURCES["idle"]) as source:
        original = ImageOps.exif_transpose(source).convert("RGBA")

    # Work on the cat's head and upper body, stopping above the paper tube.
    crop_box = (176, 48, 577, 438)
    crop = original.crop(crop_box)
    probable = [
        [
            (0.10, 0.31),
            (0.14, 0.18),
            (0.25, 0.08),
            (0.43, 0.03),
            (0.59, 0.09),
            (0.68, 0.22),
            (0.88, 0.28),
            (1.00, 0.41),
            (1.00, 1.00),
            (0.29, 1.00),
            (0.28, 0.85),
            (0.18, 0.69),
            (0.11, 0.51),
        ]
    ]
    allowed = [
        [
            (0.03, 0.30),
            (0.08, 0.14),
            (0.22, 0.02),
            (0.49, 0.00),
            (0.67, 0.08),
            (0.74, 0.19),
            (0.92, 0.25),
            (1.00, 0.36),
            (1.00, 1.00),
            (0.23, 1.00),
            (0.22, 0.86),
            (0.11, 0.71),
            (0.02, 0.49),
        ]
    ]
    alpha = _grabcut_alpha(
        crop,
        probable,
        definite_ellipses=[(0.22, 0.12, 0.58, 0.48), (0.42, 0.43, 0.94, 1.05)],
        allowed_polygons=allowed,
        iterations=7,
        feather=1.1,
    )
    result = _apply_alpha(crop, alpha)
    result = result.crop(_union_bbox([result], padding=8))
    destination = ASSET_DIR / "idle.png"
    result.save(destination, optimize=True)
    return destination


def prepare_crawl() -> Path:
    frames, durations = _read_animation(SOURCES["crawl"])
    processed = [_apply_alpha(frame, _border_connected_white_alpha(frame)) for frame in frames]
    processed = _crop_animation(processed, padding=5)
    destination = ASSET_DIR / "crawl.gif"
    _save_transparent_gif(processed, durations, destination)
    return destination


def _prepare_grabcut_animation(
    source: Path,
    destination: Path,
    probable: Sequence[Sequence[tuple[float, float]]],
    definite: Sequence[tuple[float, float, float, float]],
    allowed: Sequence[Sequence[tuple[float, float]]],
) -> Path:
    frames, durations = _read_animation(source)
    processed: list[Image.Image] = []
    for frame in frames:
        alpha = _grabcut_alpha(
            frame,
            probable,
            definite,
            allowed_polygons=allowed,
            iterations=5,
            feather=0.9,
        )
        processed.append(_apply_alpha(frame, alpha))

    # Stabilise the outline without inventing pixels: keep a majority silhouette,
    # plus each frame's genuine foreground where it lies near that silhouette.
    raw = np.stack([np.asarray(frame.getchannel("A")) for frame in processed])
    majority = (np.mean(raw >= 128, axis=0) >= 0.42).astype(np.uint8)
    nearby = cv2.dilate(
        majority,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        iterations=1,
    )
    stable: list[Image.Image] = []
    for frame, alpha in zip(frames, raw):
        binary = (((alpha >= 128) & (nearby > 0)) | (majority > 0)).astype(np.float32)
        matte = cv2.GaussianBlur(binary * 255.0, (0, 0), 0.8)
        matte[matte < 3] = 0
        matte[matte > 252] = 255
        stable.append(_apply_alpha(frame, matte.astype(np.uint8)))

    stable = _crop_animation(stable, padding=6)
    _save_transparent_gif(stable, durations, destination)
    return destination


def prepare_hiss() -> Path:
    probable = [
        [
            (0.08, 0.26),
            (0.17, 0.10),
            (0.37, 0.02),
            (0.78, 0.03),
            (0.98, 0.18),
            (1.00, 1.00),
            (0.12, 1.00),
            (0.12, 0.72),
            (0.03, 0.51),
        ]
    ]
    allowed = [
        [
            (0.02, 0.25),
            (0.11, 0.06),
            (0.34, 0.00),
            (0.84, 0.00),
            (1.00, 0.13),
            (1.00, 1.00),
            (0.06, 1.00),
            (0.06, 0.72),
            (0.00, 0.52),
        ]
    ]
    return _prepare_grabcut_animation(
        SOURCES["hiss"],
        ASSET_DIR / "hiss.gif",
        probable,
        definite=[(0.22, 0.22, 0.80, 0.72), (0.34, 0.58, 0.96, 1.10)],
        allowed=allowed,
    )


def prepare_lick() -> Path:
    probable = [
        [
            (0.08, 0.41),
            (0.13, 0.20),
            (0.30, 0.08),
            (0.70, 0.08),
            (0.88, 0.22),
            (0.97, 0.48),
            (0.93, 0.84),
            (0.77, 1.00),
            (0.18, 1.00),
            (0.05, 0.75),
        ]
    ]
    allowed = [
        [
            (0.02, 0.43),
            (0.07, 0.17),
            (0.27, 0.03),
            (0.73, 0.03),
            (0.94, 0.18),
            (1.00, 0.48),
            (0.98, 0.88),
            (0.83, 1.00),
            (0.12, 1.00),
            (0.00, 0.77),
        ]
    ]
    return _prepare_grabcut_animation(
        SOURCES["lick"],
        ASSET_DIR / "lick.gif",
        probable,
        definite=[(0.25, 0.21, 0.76, 0.72), (0.23, 0.60, 0.78, 1.08)],
        allowed=allowed,
    )


def _checkerboard(size: tuple[int, int], square: int = 12) -> Image.Image:
    width, height = size
    board = Image.new("RGB", size, (238, 238, 238))
    draw = ImageDraw.Draw(board)
    for y in range(0, height, square):
        for x in range(0, width, square):
            if (x // square + y // square) % 2:
                draw.rectangle((x, y, x + square - 1, y + square - 1), fill=(205, 205, 205))
    return board


def _sample_asset(path: Path, count: int) -> list[Image.Image]:
    with Image.open(path) as image:
        total = getattr(image, "n_frames", 1)
        indices = np.linspace(0, total - 1, min(count, total), dtype=int)
        frames: list[Image.Image] = []
        for index in indices:
            image.seek(int(index))
            frames.append(image.convert("RGBA"))
    return frames


def create_contact_sheet(paths: dict[str, Path]) -> Path:
    rows: list[tuple[str, list[Image.Image]]] = [
        ("idle.png", _sample_asset(paths["idle"], 1)),
        ("crawl.gif", _sample_asset(paths["crawl"], 4)),
        ("hiss.gif", _sample_asset(paths["hiss"], 4)),
        ("lick.gif", _sample_asset(paths["lick"], 4)),
    ]
    cell_w, cell_h, label_h, gap = 220, 190, 26, 12
    canvas_w = gap + 4 * (cell_w + gap)
    canvas_h = gap + len(rows) * (cell_h + label_h + gap)
    sheet = _checkerboard((canvas_w, canvas_h))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for row_index, (label, frames) in enumerate(rows):
        y = gap + row_index * (cell_h + label_h + gap)
        draw.rectangle((0, y, canvas_w, y + label_h), fill=(35, 35, 40))
        draw.text((gap, y + 7), label, fill=(255, 255, 255), font=font)
        for column, frame in enumerate(frames):
            thumb = frame.copy()
            thumb.thumbnail((cell_w - 16, cell_h - 16), Image.Resampling.LANCZOS)
            x0 = gap + column * (cell_w + gap)
            px = x0 + (cell_w - thumb.width) // 2
            py = y + label_h + (cell_h - thumb.height) // 2
            sheet.paste(thumb, (px, py), thumb)

    destination = ASSET_DIR / "preview-contact.png"
    sheet.save(destination, optimize=True)
    return destination


def _alpha_stats(path: Path) -> str:
    with Image.open(path) as image:
        total = getattr(image, "n_frames", 1)
        transparent = 0
        opaque = 0
        partial = 0
        for frame in ImageSequence.Iterator(image):
            alpha = np.asarray(frame.convert("RGBA").getchannel("A"))
            transparent += int(np.count_nonzero(alpha == 0))
            opaque += int(np.count_nonzero(alpha == 255))
            partial += int(np.count_nonzero((alpha > 0) & (alpha < 255)))
        return (
            f"{path.name}: size={image.size}, frames={total}, "
            f"transparent={transparent:,}, partial={partial:,}, opaque={opaque:,}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing source assets:\n" + "\n".join(missing))
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "idle": prepare_idle(),
        "crawl": prepare_crawl(),
        "hiss": prepare_hiss(),
        "lick": prepare_lick(),
    }
    preview = create_contact_sheet(outputs)
    for path in (*outputs.values(), preview):
        print(_alpha_stats(path))


if __name__ == "__main__":
    main()
