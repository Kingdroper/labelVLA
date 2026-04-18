from __future__ import annotations

from pathlib import Path

from loguru import logger
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from labelme.lerobot.dataset import LeRobotDataset
from labelme.lerobot.joint_plot_widget import JointPlotWidget
from labelme.lerobot.segment import BBox
from labelme.lerobot.segment import MotionKeypoint
from labelme.lerobot.segment import SegmentStore
from labelme.lerobot.segment_list_widget import SegmentListWidget
from labelme.lerobot.timeline_widget import TimelineWidget
from labelme.lerobot.video_viewer_widget import VideoViewerWidget


class LeRobotWindow(QtWidgets.QMainWindow):
    """Main window for LeRobot dataset annotation."""

    _dataset: LeRobotDataset
    _current_episode: int
    _current_frame: int
    _segment_store: SegmentStore

    _episode_combo: QtWidgets.QComboBox
    _joint_plot: JointPlotWidget
    _video_viewer: VideoViewerWidget
    _timeline: TimelineWidget
    _segment_list: SegmentListWidget

    def __init__(
        self,
        dataset_path: Path,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset = LeRobotDataset(dataset_path)
        self._current_episode = 0
        self._current_frame = 0
        self._segment_store = SegmentStore(dataset_path, 0)

        self.setWindowTitle(f"LeRobot - {dataset_path.name}")
        self.resize(1280, 900)

        self._init_ui()
        self._init_menu()
        self._load_episode(0)

    def _init_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Top bar: episode selector
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addWidget(QtWidgets.QLabel("Episode:"))
        self._episode_combo = QtWidgets.QComboBox()
        for i in range(self._dataset.num_episodes):
            ep = self._dataset.episodes[i]
            task_str = ", ".join(ep.get("tasks", []))
            self._episode_combo.addItem(
                f"Episode {i} ({ep['length']} frames) - {task_str}", i
            )
        self._episode_combo.currentIndexChanged.connect(self._on_episode_changed)
        top_bar.addWidget(self._episode_combo, 1)

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._save_segments)
        top_bar.addWidget(save_btn)

        main_layout.addLayout(top_bar)

        # Joint plot (~30% height)
        self._joint_plot = JointPlotWidget(
            joint_names=self._dataset.joint_names
        )
        self._joint_plot.frame_selected.connect(self._seek_to_frame)
        main_layout.addWidget(self._joint_plot, 3)

        # Video viewer (~50% height)
        self._video_viewer = VideoViewerWidget()
        self._video_viewer.set_dataset(self._dataset)
        self._video_viewer.bbox_created.connect(self._on_bbox_created)
        self._video_viewer.keypoint_added.connect(self._on_keypoint_added)
        main_layout.addWidget(self._video_viewer, 5)

        # Timeline (~10% height)
        self._timeline = TimelineWidget()
        self._timeline.frame_changed.connect(self._seek_to_frame)
        main_layout.addWidget(self._timeline)

        # Segment list as right dock
        self._segment_list = SegmentListWidget()
        self._segment_list.segment_selected.connect(self._on_segment_selected)
        self._segment_list.segments_changed.connect(self._on_segments_changed)
        self._segment_list.tracking_started.connect(self._on_tracking_started)
        self._segment_list.tracking_stopped.connect(self._on_tracking_stopped)

        dock = QtWidgets.QDockWidget("Segments", self)
        dock.setWidget(self._segment_list)
        dock.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _init_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")

        save_action = QtWidgets.QAction("&Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_segments)
        file_menu.addAction(save_action)

        close_action = QtWidgets.QAction("&Close", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

    def _load_episode(self, episode_idx: int) -> None:
        """Load an episode: parquet data, segments, and display first frame."""
        logger.info("Loading episode {}", episode_idx)

        # Stop tracking if active
        if self._segment_list.is_tracking:
            self._on_tracking_stopped()

        # Save current segments before switching
        if self._current_episode != episode_idx and self._segment_store.segments:
            self._save_segments()

        # Release old captures
        self._dataset.release_captures(self._current_episode)

        self._current_episode = episode_idx
        self._current_frame = 0

        # Load joint states
        states = self._dataset.load_episode_states(episode_idx)
        self._joint_plot.set_data(states, self._dataset.joint_names)

        # Load segments
        self._segment_store = SegmentStore(self._dataset.root, episode_idx)
        self._segment_store.load()

        total_frames = self._dataset.episode_length(episode_idx)

        # Update widgets
        self._timeline.set_range(total_frames)
        self._segment_list.set_max_frame(total_frames - 1)
        self._segment_list.set_segments(self._segment_store.segments)

        self._video_viewer.set_episode(episode_idx)

        self._update_segments_display()
        self._seek_to_frame(0)

    def _seek_to_frame(self, frame_idx: int) -> None:
        """Seek all views to the given frame."""
        self._current_frame = frame_idx

        self._timeline.set_frame(frame_idx)
        self._joint_plot.set_current_frame(frame_idx)
        self._segment_list.set_current_frame(frame_idx)

        # Get bboxes for current segment, render at per-frame position
        seg = self._segment_store.get_segment_at_frame(frame_idx)
        if seg:
            self._video_viewer.set_bboxes_at_frame(
                seg.bboxes, frame_idx, seg.start_frame, seg.end_frame
            )
        else:
            self._video_viewer.set_bboxes_at_frame([], frame_idx, 0, 0)

        # Update tracking display
        if self._segment_list.is_tracking:
            bbox = self._segment_list.get_tracking_bbox()
            seg_idx, bbox_idx = self._segment_list.get_tracking_indices()
            if bbox and 0 <= seg_idx < len(self._segment_store.segments):
                tracked_seg = self._segment_store.segments[seg_idx]
                self._video_viewer.set_tracking_mode(
                    True, bbox_idx, bbox
                )

        self._video_viewer.set_frame(frame_idx)

    def _on_episode_changed(self, index: int) -> None:
        episode_idx = self._episode_combo.itemData(index)
        if episode_idx is not None and episode_idx != self._current_episode:
            self._load_episode(episode_idx)

    def _on_segment_selected(self, seg_index: int) -> None:
        """When a segment is clicked in the list, seek to its start frame."""
        segments = self._segment_list.get_segments()
        if 0 <= seg_index < len(segments):
            self._seek_to_frame(segments[seg_index].start_frame)

    def _on_segments_changed(self) -> None:
        """Called when segments are added/edited/deleted."""
        self._segment_store.segments = self._segment_list.get_segments()
        self._update_segments_display()
        # Refresh current frame display
        self._seek_to_frame(self._current_frame)

    def _on_bbox_created(self, bbox: BBox) -> None:
        """A bbox was drawn on the head camera. Add it to the current segment."""
        self._segment_list.add_bbox_to_current_segment(bbox)
        # Refresh
        self._seek_to_frame(self._current_frame)

    def _on_tracking_started(self, seg_idx: int, bbox_idx: int) -> None:
        """Enter tracking mode for a specific bbox."""
        segments = self._segment_list.get_segments()
        if 0 <= seg_idx < len(segments):
            seg = segments[seg_idx]
            if 0 <= bbox_idx < len(seg.bboxes):
                bbox = seg.bboxes[bbox_idx]
                self._video_viewer.set_tracking_mode(True, bbox_idx, bbox)
                logger.info(
                    "Tracking started: segment {}, bbox {} ({})",
                    seg_idx, bbox_idx, bbox.label,
                )

    def _on_tracking_stopped(self) -> None:
        """Exit tracking mode."""
        self._video_viewer.set_tracking_mode(False)
        logger.info("Tracking stopped")
        # Refresh display
        self._seek_to_frame(self._current_frame)

    def _on_keypoint_added(self, cx: float, cy: float) -> None:
        """A motion keypoint was clicked in tracking mode."""
        bbox = self._segment_list.get_tracking_bbox()
        if bbox is None:
            return

        # Add or update keypoint at current frame
        frame = self._current_frame
        # Remove existing keypoint at this frame if any
        bbox.keypoints = [k for k in bbox.keypoints if k.frame != frame]
        bbox.keypoints.append(MotionKeypoint(frame=frame, cx=cx, cy=cy))
        bbox.keypoints.sort(key=lambda k: k.frame)

        logger.debug(
            "Added keypoint: frame={}, cx={:.1f}, cy={:.1f}, total={}",
            frame, cx, cy, len(bbox.keypoints),
        )

        # Refresh display
        self._segment_store.segments = self._segment_list.get_segments()
        self._on_segments_changed()

        self.statusBar().showMessage(
            f"Keypoint at frame {frame} ({len(bbox.keypoints)} total)", 2000
        )

    def _update_segments_display(self) -> None:
        """Sync segment display across timeline and joint plot."""
        segments = self._segment_store.segments
        self._timeline.set_segments(segments)
        self._joint_plot.set_segments(segments)

    def _save_segments(self) -> None:
        """Save current segments to JSON."""
        self._segment_store.segments = self._segment_list.get_segments()
        self._segment_store.save()
        logger.info(
            "Saved {} segments for episode {}",
            len(self._segment_store.segments),
            self._current_episode,
        )
        self.statusBar().showMessage(
            f"Saved {len(self._segment_store.segments)} segments", 3000
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Save segments and release resources on close."""
        if self._segment_store.segments:
            self._save_segments()
        self._dataset.close()
        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Left:
            self._seek_to_frame(max(0, self._current_frame - 1))
        elif event.key() == Qt.Key_Right:
            total = self._dataset.episode_length(self._current_episode)
            self._seek_to_frame(min(total - 1, self._current_frame + 1))
        elif event.key() == Qt.Key_Escape and self._segment_list.is_tracking:
            # Escape exits tracking mode
            self._segment_list._track_btn.setChecked(False)
        else:
            super().keyPressEvent(event)
