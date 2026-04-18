from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass
class MotionKeypoint:
    """A keyframe position for a moving bbox center."""

    frame: int
    cx: float  # center x at this frame
    cy: float  # center y at this frame


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float
    label: str
    # Motion keypoints for moving objects within a segment.
    # If empty, the bbox is static across the segment.
    # If non-empty, the center is interpolated per frame.
    keypoints: list[MotionKeypoint] = field(default_factory=list)


def interpolate_bbox_center(
    bbox: BBox, frame: int, seg_start: int, seg_end: int
) -> tuple[float, float]:
    """Return (cx, cy) for a bbox at a given frame.

    If the bbox has no keypoints, returns the original center.
    Otherwise, linearly interpolates between the nearest keypoints.
    """
    if not bbox.keypoints:
        return bbox.x + bbox.width / 2, bbox.y + bbox.height / 2

    kps = sorted(bbox.keypoints, key=lambda k: k.frame)

    # Before first keypoint — use first keypoint position
    if frame <= kps[0].frame:
        return kps[0].cx, kps[0].cy

    # After last keypoint — use last keypoint position
    if frame >= kps[-1].frame:
        return kps[-1].cx, kps[-1].cy

    # Find surrounding keypoints and interpolate
    for i in range(len(kps) - 1):
        if kps[i].frame <= frame <= kps[i + 1].frame:
            t = (frame - kps[i].frame) / (kps[i + 1].frame - kps[i].frame)
            cx = kps[i].cx + t * (kps[i + 1].cx - kps[i].cx)
            cy = kps[i].cy + t * (kps[i + 1].cy - kps[i].cy)
            return cx, cy

    # Fallback
    return bbox.x + bbox.width / 2, bbox.y + bbox.height / 2


def get_bbox_at_frame(
    bbox: BBox, frame: int, seg_start: int, seg_end: int
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) for a bbox at a specific frame.

    Width and height stay constant; only center moves.
    """
    cx, cy = interpolate_bbox_center(bbox, frame, seg_start, seg_end)
    return cx - bbox.width / 2, cy - bbox.height / 2, bbox.width, bbox.height


@dataclass
class Segment:
    start_frame: int
    end_frame: int
    text: str
    bboxes: list[BBox] = field(default_factory=list)


class SegmentStore:
    """Manages segments for one episode, persists to JSON."""

    _dataset_root: Path
    _episode_idx: int
    _segments: list[Segment]

    def __init__(self, dataset_root: Path, episode_idx: int) -> None:
        self._dataset_root = Path(dataset_root)
        self._episode_idx = episode_idx
        self._segments = []

    @property
    def file_path(self) -> Path:
        return (
            self._dataset_root
            / "segments"
            / f"episode_{self._episode_idx:06d}.json"
        )

    @property
    def segments(self) -> list[Segment]:
        return self._segments

    @segments.setter
    def segments(self, value: list[Segment]) -> None:
        self._segments = value

    def load(self) -> list[Segment]:
        """Load segments from JSON file. Returns empty list if not found."""
        if not self.file_path.is_file():
            self._segments = []
            return self._segments

        with open(self.file_path, encoding="utf-8") as f:
            data = json.load(f)

        self._segments = []
        for seg_data in data.get("segments", []):
            bboxes = []
            for b in seg_data.get("bboxes", []):
                kps = [MotionKeypoint(**k) for k in b.get("keypoints", [])]
                bboxes.append(
                    BBox(
                        x=b["x"],
                        y=b["y"],
                        width=b["width"],
                        height=b["height"],
                        label=b["label"],
                        keypoints=kps,
                    )
                )
            self._segments.append(
                Segment(
                    start_frame=seg_data["start_frame"],
                    end_frame=seg_data["end_frame"],
                    text=seg_data.get("text", ""),
                    bboxes=bboxes,
                )
            )
        return self._segments

    def save(self, segments: list[Segment] | None = None) -> None:
        """Save segments to JSON file."""
        if segments is not None:
            self._segments = segments

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "episode_index": self._episode_idx,
            "segments": [asdict(seg) for seg in self._segments],
        }

        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_segment(self, segment: Segment) -> None:
        self._segments.append(segment)

    def remove_segment(self, index: int) -> None:
        if 0 <= index < len(self._segments):
            self._segments.pop(index)

    def update_segment(self, index: int, segment: Segment) -> None:
        if 0 <= index < len(self._segments):
            self._segments[index] = segment

    def get_segment_at_frame(self, frame_idx: int) -> Segment | None:
        """Return the segment that contains the given frame, or None."""
        for seg in self._segments:
            if seg.start_frame <= frame_idx <= seg.end_frame:
                return seg
        return None
