from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from loguru import logger
from numpy.typing import NDArray


class LeRobotDataset:
    """Read-only access to a LeRobot v2 dataset folder."""

    root: Path
    info: dict
    episodes: list[dict]
    fps: int
    camera_keys: list[str]
    joint_names: list[str]

    _video_captures: dict[str, cv2.VideoCapture]

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._video_captures = {}

        with open(self.root / "meta" / "info.json") as f:
            self.info = json.load(f)

        self.fps = self.info["fps"]

        self.episodes = []
        with open(self.root / "meta" / "episodes.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.episodes.append(json.loads(line))

        self.camera_keys = [
            k
            for k, v in self.info["features"].items()
            if v.get("dtype") == "video"
        ]

        state_feature = self.info["features"].get("observation.state", {})
        self.joint_names = state_feature.get("names", [])

    @staticmethod
    def is_lerobot_dataset(path: Path) -> bool:
        """Check if path looks like a LeRobot dataset."""
        return (Path(path) / "meta" / "info.json").is_file()

    @property
    def num_episodes(self) -> int:
        return len(self.episodes)

    def episode_length(self, episode_idx: int) -> int:
        """Return frame count for the given episode."""
        return self.episodes[episode_idx]["length"]

    def _get_episode_chunk(self, episode_idx: int) -> int:
        chunks_size = self.info.get("chunks_size", 1000)
        return episode_idx // chunks_size

    def _get_parquet_path(self, episode_idx: int) -> Path:
        chunk = self._get_episode_chunk(episode_idx)
        return self.root / f"data/chunk-{chunk:03d}/episode_{episode_idx:06d}.parquet"

    def load_episode_states(self, episode_idx: int) -> NDArray[np.float32]:
        """Return (num_frames, N) array of observation.state for an episode."""
        parquet_path = self._get_parquet_path(episode_idx)
        df = pd.read_parquet(parquet_path, columns=["observation.state"])
        states = np.array(df["observation.state"].tolist(), dtype=np.float32)
        return states

    def load_episode_dataframe(self, episode_idx: int) -> pd.DataFrame:
        """Return the full parquet dataframe for an episode."""
        parquet_path = self._get_parquet_path(episode_idx)
        return pd.read_parquet(parquet_path)

    def get_video_path(self, episode_idx: int, camera_key: str) -> Path:
        chunk = self._get_episode_chunk(episode_idx)
        return (
            self.root
            / f"videos/chunk-{chunk:03d}/{camera_key}/episode_{episode_idx:06d}.mp4"
        )

    def _get_capture(
        self, episode_idx: int, camera_key: str
    ) -> cv2.VideoCapture:
        cache_key = f"{episode_idx}:{camera_key}"
        if cache_key not in self._video_captures:
            video_path = self.get_video_path(episode_idx, camera_key)
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise RuntimeError(f"Cannot open video: {video_path}")
            self._video_captures[cache_key] = cap
            logger.debug("Opened video capture: {}", video_path)
        return self._video_captures[cache_key]

    def extract_frame(
        self, episode_idx: int, camera_key: str, frame_idx: int
    ) -> NDArray[np.uint8]:
        """Decode a single frame from video. Returns BGR numpy array (H, W, 3)."""
        cap = self._get_capture(episode_idx, camera_key)
        current_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if current_pos != frame_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError(
                f"Failed to read frame {frame_idx} from "
                f"episode {episode_idx} camera {camera_key}"
            )
        return frame

    def release_captures(self, episode_idx: int | None = None) -> None:
        """Release cached VideoCapture objects."""
        keys_to_remove = []
        for key, cap in self._video_captures.items():
            if episode_idx is None or key.startswith(f"{episode_idx}:"):
                cap.release()
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._video_captures[key]

    def close(self) -> None:
        """Release all resources."""
        self.release_captures()
