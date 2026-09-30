"""Crop and scale a landed screenshot so a reviewer can actually read it.

A full-page capture of a long screen is one very tall image. Handed that
file, a reviewer reading through an agent harness sees it downsampled to
fit a viewport -- every label in it becomes unreadable, and the evidence
proves nothing to the person who has to judge it. The fix is not a second
capture at a different size: the bytes already recorded hold the detail,
and the reviewer only needs to say which part to look at and how big.

So ``yoke qa artifact read`` takes ``--region`` and ``--scale`` and renders
the recorded bytes into the file it was going to write anyway. The stored
artifact is never touched -- a view is a way of reading evidence, not a new
version of it -- and the reported ``artifact_view`` says exactly which
pixels the reader is holding, so a finding can name the region it was seen
in.

Backend follows the same rule as the project's other raster path: Pillow if
it is installed, else macOS ``sips``, else a refusal naming both fixes
rather than a silent pass-through of an image nobody can read.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

#: The literal a ``--region`` value is written as.
REGION_FORMAT = "x,y,w,h"

#: Largest magnification a single view may ask for. A reviewer enlarging to
#: read small text needs a handful of times, and the cap is what stops a
#: mistyped scale from trying to allocate an image the machine cannot hold.
MAX_SCALE = 8.0

#: Content types this renderer knows how to crop and scale.
SUPPORTED_CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp")


class ArtifactViewError(Exception):
    """A view could not be rendered, with the reason and the fix named."""


@dataclass(frozen=True)
class ImageRegion:
    """A pixel rectangle of a captured image, in image coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]


def parse_region(text: str) -> ImageRegion:
    """Parse a ``x,y,w,h`` region, refusing anything that cannot be a crop."""
    parts = [part.strip() for part in str(text).split(",")]
    if len(parts) != 4:
        raise ArtifactViewError(
            f"--region needs four comma-separated integers ({REGION_FORMAT}), "
            f"got {text!r}. Example: --region 0,0,1440,900"
        )
    numbers = []
    for name, part in zip(("x", "y", "w", "h"), parts):
        try:
            numbers.append(int(part))
        except ValueError:
            raise ArtifactViewError(
                f"--region {name} must be an integer number of pixels, got "
                f"{part!r}. Example: --region 0,0,1440,900"
            ) from None
    x, y, width, height = numbers
    if x < 0 or y < 0:
        raise ArtifactViewError(
            f"--region x and y are pixel offsets from the top-left and cannot "
            f"be negative, got x={x}, y={y}."
        )
    if width <= 0 or height <= 0:
        raise ArtifactViewError(
            f"--region w and h must be positive, got w={width}, h={height}. A "
            "region with no area would render an empty file."
        )
    return ImageRegion(x=x, y=y, width=width, height=height)


def parse_scale(text: str) -> float:
    """Parse a ``--scale`` multiplier, refusing values that cannot render."""
    try:
        scale = float(str(text).strip())
    except ValueError:
        raise ArtifactViewError(
            f"--scale must be a number, got {text!r}. Use 0.5 to halve or 2 "
            "to double the rendered size."
        ) from None
    if scale <= 0:
        raise ArtifactViewError(
            f"--scale must be greater than zero, got {scale}. Use 0.5 to "
            "halve or 2 to double the rendered size."
        )
    if scale > MAX_SCALE:
        raise ArtifactViewError(
            f"--scale {scale} exceeds the {MAX_SCALE} maximum. Enlarge a "
            "narrower --region instead: a view of the part you are reading "
            "stays legible where a magnified whole page does not."
        )
    return scale


def refuse_unsupported_content_type(content_type: Optional[str]) -> None:
    """Refuse a view of evidence that is not a raster image."""
    base = str(content_type or "").split(";", 1)[0].strip().lower()
    if base in SUPPORTED_CONTENT_TYPES:
        return
    named = base or "unknown"
    raise ArtifactViewError(
        f"--region and --scale render a raster image, and this artifact is "
        f"{named}. Re-read it without those flags to land the bytes as "
        "recorded."
    )


def apply_artifact_view(
    path: Path,
    *,
    region: Optional[ImageRegion] = None,
    scale: Optional[float] = None,
) -> dict[str, Any]:
    """Render *path* in place as the requested region and scale.

    Returns what was applied -- source size, region, scale, rendered size and
    the backend that did it -- so the caller can report the view rather than
    leaving the reader to infer which pixels they received.
    """
    if region is None and scale is None:
        raise ArtifactViewError(
            "apply_artifact_view needs a region, a scale, or both; it was "
            "called with neither, which would rewrite the file for nothing."
        )

    backend = _select_backend()
    source_width, source_height = backend.dimensions(path)

    if region is not None:
        if region.right > source_width or region.bottom > source_height:
            raise ArtifactViewError(
                f"--region {','.join(str(v) for v in region.as_list())} falls "
                f"outside the {source_width}x{source_height} image: it would "
                f"need {region.right}x{region.bottom}. Read the artifact once "
                "without --region to see the whole capture, then name a "
                "region inside it."
            )
        view_width, view_height = region.width, region.height
    else:
        view_width, view_height = source_width, source_height

    target_width = view_width
    target_height = view_height
    if scale is not None:
        target_width = max(1, round(view_width * scale))
        target_height = max(1, round(view_height * scale))

    backend.render(
        path,
        region=region,
        target_size=(target_width, target_height),
    )

    return {
        "source_size": [source_width, source_height],
        "region": region.as_list() if region is not None else None,
        "scale": scale,
        "size": [target_width, target_height],
        "backend": backend.name,
    }


class _PillowBackend:
    """Render with Pillow, which handles every format it opened."""

    name = "pillow"

    def dimensions(self, path: Path) -> tuple[int, int]:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            return image.size

    def render(
        self,
        path: Path,
        *,
        region: Optional[ImageRegion],
        target_size: tuple[int, int],
    ) -> None:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            image.load()
            view = image
            if region is not None:
                view = view.crop(
                    (region.x, region.y, region.right, region.bottom)
                )
            if view.size != target_size:
                view = view.resize(target_size, Image.LANCZOS)
            view.save(path)


class _SipsBackend:
    """Render with macOS ``sips``, in one crop call and one resample call."""

    name = "sips"

    def dimensions(self, path: Path) -> tuple[int, int]:
        output = _run_sips(
            ["-g", "pixelWidth", "-g", "pixelHeight", str(path)]
        )
        width = height = None
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("pixelWidth:"):
                width = int(stripped.split(":", 1)[1])
            elif stripped.startswith("pixelHeight:"):
                height = int(stripped.split(":", 1)[1])
        if width is None or height is None:
            raise ArtifactViewError(
                f"sips did not report pixel dimensions for {path}, so the "
                "region cannot be checked against the image. Install Pillow "
                "(`pip install 'yoke-cli[images]'`) to render this view."
            )
        return width, height

    def render(
        self,
        path: Path,
        *,
        region: Optional[ImageRegion],
        target_size: tuple[int, int],
    ) -> None:
        if region is not None:
            # sips crops around the image centre unless an offset is given,
            # so the offset is what makes this the named rectangle.
            _run_sips([
                "--cropOffset", str(region.y), str(region.x),
                "-c", str(region.height), str(region.width),
                str(path), "--out", str(path),
            ])
            current = (region.width, region.height)
        else:
            current = self.dimensions(path)
        if current != target_size:
            # -z takes height then width, unlike every other pair here.
            _run_sips([
                "-z", str(target_size[1]), str(target_size[0]),
                str(path), "--out", str(path),
            ])


def _run_sips(arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["sips", *arguments],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ArtifactViewError(
            "sips could not render this view: "
            f"{(exc.stderr or exc.stdout or '').strip() or 'no output'}. "
            "Install Pillow (`pip install 'yoke-cli[images]'`) for a "
            "platform-independent renderer."
        ) from None
    return completed.stdout


def _select_backend() -> Any:
    try:
        import PIL  # type: ignore  # noqa: F401
    except ImportError:
        pass
    else:
        return _PillowBackend()
    if shutil.which("sips"):
        return _SipsBackend()
    raise ArtifactViewError(
        "no image renderer is available, so --region and --scale cannot be "
        "applied. Install Pillow with `pip install 'yoke-cli[images]'`, or "
        "run the read on macOS where `sips` provides the fallback. Re-reading "
        "without those flags still lands the recorded bytes."
    )


__all__ = [
    "ArtifactViewError",
    "ImageRegion",
    "MAX_SCALE",
    "REGION_FORMAT",
    "SUPPORTED_CONTENT_TYPES",
    "apply_artifact_view",
    "parse_region",
    "parse_scale",
    "refuse_unsupported_content_type",
]
