from __future__ import annotations

from PyQt5 import QtCore
from PyQt5 import QtWidgets

from labelme.lerobot.segment import BBox
from labelme.lerobot.segment import Segment


class _SegmentEditDialog(QtWidgets.QDialog):
    """Dialog for creating or editing a segment."""

    _start_spin: QtWidgets.QSpinBox
    _end_spin: QtWidgets.QSpinBox
    _text_edit: QtWidgets.QLineEdit

    def __init__(
        self,
        max_frame: int,
        segment: Segment | None = None,
        start_frame: int | None = None,
        end_frame: int | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Segment" if segment else "Add Segment")
        self.setMinimumWidth(300)

        layout = QtWidgets.QFormLayout(self)

        self._start_spin = QtWidgets.QSpinBox()
        self._start_spin.setRange(0, max_frame)
        self._end_spin = QtWidgets.QSpinBox()
        self._end_spin.setRange(0, max_frame)

        self._text_edit = QtWidgets.QLineEdit()
        self._text_edit.setPlaceholderText("Segment description...")

        if segment:
            self._start_spin.setValue(segment.start_frame)
            self._end_spin.setValue(segment.end_frame)
            self._text_edit.setText(segment.text)
        if start_frame is not None:
            self._start_spin.setValue(start_frame)
        if end_frame is not None:
            self._end_spin.setValue(end_frame)

        layout.addRow("Start Frame:", self._start_spin)
        layout.addRow("End Frame:", self._end_spin)
        layout.addRow("Text:", self._text_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self) -> tuple[int, int, str]:
        return (
            self._start_spin.value(),
            self._end_spin.value(),
            self._text_edit.text(),
        )


class SegmentListWidget(QtWidgets.QWidget):
    """Widget listing segments with add/edit/delete and bbox tracking."""

    segment_selected = QtCore.pyqtSignal(int)  # segment index
    segments_changed = QtCore.pyqtSignal()
    tracking_started = QtCore.pyqtSignal(int, int)  # segment index, bbox index
    tracking_stopped = QtCore.pyqtSignal()

    _segments: list[Segment]
    _list_widget: QtWidgets.QListWidget
    _bbox_list: QtWidgets.QListWidget
    _max_frame: int
    _current_frame: int
    _tracking_active: bool
    _tracking_seg_idx: int
    _tracking_bbox_idx: int

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments = []
        self._max_frame = 0
        self._current_frame = 0
        self._tracking_active = False
        self._tracking_seg_idx = -1
        self._tracking_bbox_idx = -1
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # === Segment section ===
        title = QtWidgets.QLabel("Segments")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        self._list_widget = QtWidgets.QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_seg_row_changed)
        layout.addWidget(self._list_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("+ Add")
        add_btn.clicked.connect(self._add_segment)
        add_at_current_btn = QtWidgets.QPushButton("+ At Current")
        add_at_current_btn.setToolTip("Add segment starting at current frame")
        add_at_current_btn.clicked.connect(self._add_segment_at_current)
        edit_btn = QtWidgets.QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_segment)
        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_segment)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(add_at_current_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)

        # === BBox section (for the selected segment) ===
        bbox_title = QtWidgets.QLabel("BBoxes in Segment")
        bbox_title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(bbox_title)

        self._bbox_list = QtWidgets.QListWidget()
        self._bbox_list.setMaximumHeight(120)
        layout.addWidget(self._bbox_list)

        bbox_btn_layout = QtWidgets.QHBoxLayout()

        self._track_btn = QtWidgets.QPushButton("Track Object")
        self._track_btn.setToolTip(
            "Enter tracking mode: click on the image at different frames\n"
            "to define the motion path of the selected bbox"
        )
        self._track_btn.setCheckable(True)
        self._track_btn.toggled.connect(self._on_track_toggled)

        clear_kp_btn = QtWidgets.QPushButton("Clear Path")
        clear_kp_btn.setToolTip("Remove all motion keypoints for the selected bbox")
        clear_kp_btn.clicked.connect(self._clear_keypoints)

        del_bbox_btn = QtWidgets.QPushButton("Del BBox")
        del_bbox_btn.clicked.connect(self._delete_bbox)

        bbox_btn_layout.addWidget(self._track_btn)
        bbox_btn_layout.addWidget(clear_kp_btn)
        bbox_btn_layout.addWidget(del_bbox_btn)
        layout.addLayout(bbox_btn_layout)

        # Tracking status
        self._track_status = QtWidgets.QLabel("")
        self._track_status.setStyleSheet("color: #ffa500; font-size: 10px;")
        layout.addWidget(self._track_status)

    def set_segments(self, segments: list[Segment]) -> None:
        self._segments = segments
        self._refresh_seg_list()

    def set_max_frame(self, max_frame: int) -> None:
        self._max_frame = max_frame

    def set_current_frame(self, frame: int) -> None:
        self._current_frame = frame
        if self._tracking_active:
            self._track_status.setText(
                f"Tracking: frame {frame} — click on image to set keypoint"
            )

    def get_segments(self) -> list[Segment]:
        return self._segments

    @property
    def is_tracking(self) -> bool:
        return self._tracking_active

    def get_tracking_bbox(self) -> BBox | None:
        """Return the bbox being tracked, or None."""
        if not self._tracking_active:
            return None
        if 0 <= self._tracking_seg_idx < len(self._segments):
            seg = self._segments[self._tracking_seg_idx]
            if 0 <= self._tracking_bbox_idx < len(seg.bboxes):
                return seg.bboxes[self._tracking_bbox_idx]
        return None

    def get_tracking_indices(self) -> tuple[int, int]:
        return self._tracking_seg_idx, self._tracking_bbox_idx

    def _refresh_seg_list(self) -> None:
        self._list_widget.clear()
        for i, seg in enumerate(self._segments):
            bbox_count = len(seg.bboxes)
            moving_count = sum(1 for b in seg.bboxes if b.keypoints)
            text = (
                f"#{i + 1}: [{seg.start_frame}-{seg.end_frame}] "
                f'"{seg.text}" ({bbox_count} boxes'
            )
            if moving_count:
                text += f", {moving_count} moving"
            text += ")"
            self._list_widget.addItem(text)
        self._refresh_bbox_list()

    def _refresh_bbox_list(self) -> None:
        self._bbox_list.clear()
        seg_idx = self._list_widget.currentRow()
        if seg_idx < 0 or seg_idx >= len(self._segments):
            return
        seg = self._segments[seg_idx]
        for i, bbox in enumerate(seg.bboxes):
            status = ""
            if bbox.keypoints:
                status = f" [moving: {len(bbox.keypoints)} keypoints]"
            self._bbox_list.addItem(
                f'{bbox.label} ({bbox.width:.0f}x{bbox.height:.0f}){status}'
            )

    def _on_seg_row_changed(self, row: int) -> None:
        self._refresh_bbox_list()
        if 0 <= row < len(self._segments):
            self.segment_selected.emit(row)

    def _on_track_toggled(self, checked: bool) -> None:
        if checked:
            seg_idx = self._list_widget.currentRow()
            bbox_idx = self._bbox_list.currentRow()
            if seg_idx < 0 or bbox_idx < 0:
                self._track_btn.setChecked(False)
                QtWidgets.QMessageBox.information(
                    self,
                    "Select BBox",
                    "Please select a segment and a bbox to track.",
                )
                return
            self._tracking_active = True
            self._tracking_seg_idx = seg_idx
            self._tracking_bbox_idx = bbox_idx
            bbox = self._segments[seg_idx].bboxes[bbox_idx]
            self._track_status.setText(
                f'Tracking "{bbox.label}" — click on image at different frames'
            )
            self._track_btn.setStyleSheet("background-color: #ffa500;")
            self.tracking_started.emit(seg_idx, bbox_idx)
        else:
            self._tracking_active = False
            self._tracking_seg_idx = -1
            self._tracking_bbox_idx = -1
            self._track_status.setText("")
            self._track_btn.setStyleSheet("")
            self.tracking_stopped.emit()

    def _clear_keypoints(self) -> None:
        seg_idx = self._list_widget.currentRow()
        bbox_idx = self._bbox_list.currentRow()
        if seg_idx < 0 or bbox_idx < 0:
            return
        seg = self._segments[seg_idx]
        if bbox_idx < len(seg.bboxes):
            seg.bboxes[bbox_idx].keypoints.clear()
            self._refresh_bbox_list()
            self.segments_changed.emit()

    def _delete_bbox(self) -> None:
        seg_idx = self._list_widget.currentRow()
        bbox_idx = self._bbox_list.currentRow()
        if seg_idx < 0 or bbox_idx < 0:
            return
        seg = self._segments[seg_idx]
        if bbox_idx < len(seg.bboxes):
            # Stop tracking if this bbox is being tracked
            if self._tracking_active and self._tracking_bbox_idx == bbox_idx:
                self._track_btn.setChecked(False)
            seg.bboxes.pop(bbox_idx)
            self._refresh_seg_list()
            self.segments_changed.emit()

    def add_bbox_to_current_segment(self, bbox: BBox) -> None:
        """Add a bbox to the segment containing the current frame."""
        for seg in self._segments:
            if seg.start_frame <= self._current_frame <= seg.end_frame:
                seg.bboxes.append(bbox)
                self._refresh_seg_list()
                self.segments_changed.emit()
                return
        QtWidgets.QMessageBox.warning(
            self,
            "No Segment",
            "No segment covers the current frame. "
            "Please create a segment first.",
        )

    def _add_segment(self) -> None:
        dlg = _SegmentEditDialog(max_frame=self._max_frame, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            start, end, text = dlg.get_values()
            if start > end:
                start, end = end, start
            self._segments.append(Segment(start_frame=start, end_frame=end, text=text))
            self._segments.sort(key=lambda s: s.start_frame)
            self._refresh_seg_list()
            self.segments_changed.emit()

    def _add_segment_at_current(self) -> None:
        dlg = _SegmentEditDialog(
            max_frame=self._max_frame,
            start_frame=self._current_frame,
            end_frame=min(self._current_frame + 30, self._max_frame),
            parent=self,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            start, end, text = dlg.get_values()
            if start > end:
                start, end = end, start
            self._segments.append(Segment(start_frame=start, end_frame=end, text=text))
            self._segments.sort(key=lambda s: s.start_frame)
            self._refresh_seg_list()
            self.segments_changed.emit()

    def _edit_segment(self) -> None:
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._segments):
            return
        seg = self._segments[row]
        dlg = _SegmentEditDialog(
            max_frame=self._max_frame, segment=seg, parent=self
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            start, end, text = dlg.get_values()
            if start > end:
                start, end = end, start
            seg.start_frame = start
            seg.end_frame = end
            seg.text = text
            self._segments.sort(key=lambda s: s.start_frame)
            self._refresh_seg_list()
            self.segments_changed.emit()

    def _delete_segment(self) -> None:
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._segments):
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Segment",
            f"Delete segment #{row + 1}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            # Stop tracking if tracking a bbox in this segment
            if self._tracking_active and self._tracking_seg_idx == row:
                self._track_btn.setChecked(False)
            self._segments.pop(row)
            self._refresh_seg_list()
            self.segments_changed.emit()
