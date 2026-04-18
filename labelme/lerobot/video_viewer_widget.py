from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from labelme.lerobot.dataset import LeRobotDataset
from labelme.lerobot.segment import BBox
from labelme.lerobot.segment import get_bbox_at_frame
from labelme.lerobot.segment import interpolate_bbox_center


def _cv_to_qimage(frame: NDArray[np.uint8]) -> QtGui.QImage:
    """Convert BGR numpy array to QImage."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    return QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888).copy()


class _HeadCameraWidget(QtWidgets.QWidget):
    """Displays head camera frame with bbox overlay, drawing, and tracking support."""

    bbox_created = QtCore.pyqtSignal(BBox)
    keypoint_added = QtCore.pyqtSignal(float, float)  # image cx, cy

    _pixmap: QtGui.QPixmap | None
    _bboxes: list[BBox]
    _bbox_rects: list[tuple[float, float, float, float]]  # per-frame resolved (x,y,w,h)
    _drawing: bool
    _draw_start: QtCore.QPointF | None
    _draw_end: QtCore.QPointF | None
    _image_rect: QtCore.QRectF
    _image_size: QtCore.QSizeF
    _tracking_mode: bool
    _selected_bbox_idx: int  # -1 = none
    _tracking_bbox: BBox | None  # the bbox being tracked (for path display)
    _current_frame: int
    _seg_start: int
    _seg_end: int

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = None
        self._bboxes = []
        self._bbox_rects = []
        self._drawing = False
        self._draw_start = None
        self._draw_end = None
        self._image_rect = QtCore.QRectF()
        self._image_size = QtCore.QSizeF(1, 1)
        self._tracking_mode = False
        self._selected_bbox_idx = -1
        self._tracking_bbox = None
        self._current_frame = 0
        self._seg_start = 0
        self._seg_end = 0
        self.setMinimumSize(320, 240)

    def set_frame(self, pixmap: QtGui.QPixmap) -> None:
        self._pixmap = pixmap
        self._image_size = QtCore.QSizeF(pixmap.width(), pixmap.height())
        self.update()

    def set_bboxes_at_frame(
        self,
        bboxes: list[BBox],
        frame: int,
        seg_start: int,
        seg_end: int,
    ) -> None:
        """Set bboxes and resolve their positions at the given frame."""
        self._bboxes = bboxes
        self._current_frame = frame
        self._seg_start = seg_start
        self._seg_end = seg_end
        self._bbox_rects = [
            get_bbox_at_frame(b, frame, seg_start, seg_end) for b in bboxes
        ]
        self.update()

    def set_tracking_mode(
        self, enabled: bool, bbox_idx: int = -1, bbox: BBox | None = None
    ) -> None:
        self._tracking_mode = enabled
        self._selected_bbox_idx = bbox_idx
        self._tracking_bbox = bbox
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def _compute_image_rect(self) -> QtCore.QRectF:
        if self._pixmap is None:
            return QtCore.QRectF()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        sw, sh = pw * scale, ph * scale
        x = (ww - sw) / 2
        y = (wh - sh) / 2
        return QtCore.QRectF(x, y, sw, sh)

    def _widget_to_image(self, pos: QtCore.QPointF) -> QtCore.QPointF:
        r = self._image_rect
        if r.width() == 0 or r.height() == 0:
            return QtCore.QPointF(0, 0)
        ix = (pos.x() - r.x()) / r.width() * self._image_size.width()
        iy = (pos.y() - r.y()) / r.height() * self._image_size.height()
        return QtCore.QPointF(
            max(0, min(ix, self._image_size.width())),
            max(0, min(iy, self._image_size.height())),
        )

    def _image_to_widget(self, pos: QtCore.QPointF) -> QtCore.QPointF:
        r = self._image_rect
        wx = pos.x() / self._image_size.width() * r.width() + r.x()
        wy = pos.y() / self._image_size.height() * r.height() + r.y()
        return QtCore.QPointF(wx, wy)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(40, 40, 40))

        if self._pixmap is None:
            painter.end()
            return

        self._image_rect = self._compute_image_rect()
        painter.drawPixmap(self._image_rect.toRect(), self._pixmap)

        # Draw bboxes at their per-frame position
        for i, (bbox, rect) in enumerate(zip(self._bboxes, self._bbox_rects)):
            bx, by, bw, bh = rect
            is_selected = i == self._selected_bbox_idx and self._tracking_mode

            # Box color: yellow for selected/tracking, green for normal, cyan for moving
            if is_selected:
                pen = QtGui.QPen(QtGui.QColor(255, 255, 0), 3)
            elif bbox.keypoints:
                pen = QtGui.QPen(QtGui.QColor(0, 200, 255), 2)
            else:
                pen = QtGui.QPen(QtGui.QColor(0, 255, 0), 2)

            painter.setPen(pen)
            tl = self._image_to_widget(QtCore.QPointF(bx, by))
            br = self._image_to_widget(QtCore.QPointF(bx + bw, by + bh))
            draw_rect = QtCore.QRectF(tl, br)
            painter.drawRect(draw_rect)

            # Label
            painter.setPen(Qt.white)
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            suffix = " [tracking]" if is_selected else (" [moving]" if bbox.keypoints else "")
            painter.drawText(
                draw_rect.topLeft() + QtCore.QPointF(2, -3),
                bbox.label + suffix,
            )

        # Draw motion path for the tracked bbox
        if self._tracking_mode and self._tracking_bbox and self._tracking_bbox.keypoints:
            kps = sorted(self._tracking_bbox.keypoints, key=lambda k: k.frame)
            # Draw keypoint dots
            for kp in kps:
                wp = self._image_to_widget(QtCore.QPointF(kp.cx, kp.cy))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QtGui.QColor(255, 0, 0, 200))
                painter.drawEllipse(wp, 5, 5)
                # Frame number
                painter.setPen(QtGui.QColor(255, 100, 100))
                font = painter.font()
                font.setPointSize(7)
                painter.setFont(font)
                painter.drawText(wp + QtCore.QPointF(7, -2), str(kp.frame))

            # Draw interpolated path as a polyline
            if len(kps) >= 2:
                pen = QtGui.QPen(QtGui.QColor(255, 100, 100, 180), 1, Qt.DashLine)
                painter.setPen(pen)
                for f in range(self._seg_start, self._seg_end + 1):
                    cx, cy = interpolate_bbox_center(
                        self._tracking_bbox, f, self._seg_start, self._seg_end
                    )
                    wp = self._image_to_widget(QtCore.QPointF(cx, cy))
                    if f == self._seg_start:
                        path = QtGui.QPainterPath(wp)
                    else:
                        path.lineTo(wp)  # type: ignore[possibly-undefined]
                if self._seg_end > self._seg_start:
                    painter.drawPath(path)  # type: ignore[possibly-undefined]

        # Draw in-progress rectangle
        if self._drawing and self._draw_start and self._draw_end:
            pen = QtGui.QPen(QtGui.QColor(255, 255, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(QtCore.QRectF(self._draw_start, self._draw_end))

        # Tracking mode indicator
        if self._tracking_mode:
            painter.setPen(QtGui.QColor(255, 255, 0))
            font = painter.font()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(10, 20, "TRACKING MODE - Click to set keypoint")

        painter.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._pixmap is None:
            return

        if self._tracking_mode:
            # In tracking mode, click to add a motion keypoint
            img_pos = self._widget_to_image(QtCore.QPointF(event.pos()))
            self.keypoint_added.emit(img_pos.x(), img_pos.y())
        else:
            # Normal mode: draw bbox
            self._drawing = True
            self._draw_start = event.pos()
            self._draw_end = event.pos()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drawing:
            self._draw_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drawing:
            self._drawing = False
            if self._draw_start and self._draw_end:
                p1 = self._widget_to_image(QtCore.QPointF(self._draw_start))
                p2 = self._widget_to_image(QtCore.QPointF(self._draw_end))
                x = min(p1.x(), p2.x())
                y = min(p1.y(), p2.y())
                w = abs(p2.x() - p1.x())
                h = abs(p2.y() - p1.y())
                if w > 5 and h > 5:
                    label, ok = QtWidgets.QInputDialog.getText(
                        self, "BBox Label", "Enter label for this box:"
                    )
                    if ok and label:
                        bbox = BBox(
                            x=round(x, 1),
                            y=round(y, 1),
                            width=round(w, 1),
                            height=round(h, 1),
                            label=label,
                        )
                        self.bbox_created.emit(bbox)
            self._draw_start = None
            self._draw_end = None
            self.update()


class _SmallCameraWidget(QtWidgets.QWidget):
    """Displays a small camera frame (wrist cameras)."""

    _pixmap: QtGui.QPixmap | None
    _title: str

    def __init__(
        self, title: str = "", parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._pixmap = None
        self._title = title
        self.setMinimumSize(160, 120)

    def set_frame(self, pixmap: QtGui.QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(40, 40, 40))

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

        painter.setPen(QtGui.QColor(200, 200, 200))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(4, 14, self._title)
        painter.end()


class VideoViewerWidget(QtWidgets.QWidget):
    """Multi-camera video display: head camera (large) + wrist cameras (small)."""

    bbox_created = QtCore.pyqtSignal(BBox)
    keypoint_added = QtCore.pyqtSignal(float, float)  # forwarded from head camera

    _dataset: LeRobotDataset | None
    _episode_idx: int
    _head_camera: _HeadCameraWidget
    _wrist_cameras: dict[str, _SmallCameraWidget]
    _head_key: str

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._dataset = None
        self._episode_idx = 0
        self._head_key = "observation.images.head"
        self._wrist_cameras = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._head_camera = _HeadCameraWidget()
        self._head_camera.bbox_created.connect(self.bbox_created)
        self._head_camera.keypoint_added.connect(self.keypoint_added)
        layout.addWidget(self._head_camera, 3)

        wrist_layout = QtWidgets.QVBoxLayout()
        wrist_layout.setSpacing(4)

        self._left_wrist = _SmallCameraWidget("Left Wrist")
        self._right_wrist = _SmallCameraWidget("Right Wrist")
        wrist_layout.addWidget(self._left_wrist)
        wrist_layout.addWidget(self._right_wrist)
        self._wrist_cameras = {
            "observation.images.left_wrist": self._left_wrist,
            "observation.images.right_wrist": self._right_wrist,
        }

        layout.addLayout(wrist_layout, 1)

    def set_dataset(self, dataset: LeRobotDataset) -> None:
        self._dataset = dataset

    def set_episode(self, episode_idx: int) -> None:
        self._episode_idx = episode_idx

    def set_bboxes_at_frame(
        self,
        bboxes: list[BBox],
        frame: int,
        seg_start: int,
        seg_end: int,
    ) -> None:
        self._head_camera.set_bboxes_at_frame(bboxes, frame, seg_start, seg_end)

    def set_tracking_mode(
        self, enabled: bool, bbox_idx: int = -1, bbox: BBox | None = None
    ) -> None:
        self._head_camera.set_tracking_mode(enabled, bbox_idx, bbox)

    def set_frame(self, frame_idx: int) -> None:
        """Update all camera views to the given frame."""
        if self._dataset is None:
            return

        if self._head_key in self._dataset.camera_keys:
            try:
                bgr = self._dataset.extract_frame(
                    self._episode_idx, self._head_key, frame_idx
                )
                qimg = _cv_to_qimage(bgr)
                self._head_camera.set_frame(QtGui.QPixmap.fromImage(qimg))
            except RuntimeError:
                pass

        for cam_key, widget in self._wrist_cameras.items():
            if cam_key in self._dataset.camera_keys:
                try:
                    bgr = self._dataset.extract_frame(
                        self._episode_idx, cam_key, frame_idx
                    )
                    qimg = _cv_to_qimage(bgr)
                    widget.set_frame(QtGui.QPixmap.fromImage(qimg))
                except RuntimeError:
                    pass
