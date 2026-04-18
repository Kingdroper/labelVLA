from __future__ import annotations

from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from labelme.lerobot.segment import Segment

# Distinct colors for segments
_SEGMENT_COLORS: list[QtGui.QColor] = [
    QtGui.QColor(76, 175, 80, 160),
    QtGui.QColor(33, 150, 243, 160),
    QtGui.QColor(255, 152, 0, 160),
    QtGui.QColor(156, 39, 176, 160),
    QtGui.QColor(244, 67, 54, 160),
    QtGui.QColor(0, 188, 212, 160),
    QtGui.QColor(255, 235, 59, 160),
    QtGui.QColor(121, 85, 72, 160),
]


class _SegmentBar(QtWidgets.QWidget):
    """Custom painted bar showing colored segment blocks."""

    clicked = QtCore.pyqtSignal(int)  # frame index

    _total_frames: int
    _segments: list[Segment]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._total_frames = 1
        self._segments = []
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)
        self.setCursor(Qt.PointingHandCursor)

    def set_data(self, total_frames: int, segments: list[Segment]) -> None:
        self._total_frames = max(total_frames, 1)
        self._segments = segments
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QtGui.QColor(60, 60, 60))

        # Draw segments
        for i, seg in enumerate(self._segments):
            color = _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)]
            x1 = int(seg.start_frame / self._total_frames * w)
            x2 = int((seg.end_frame + 1) / self._total_frames * w)
            painter.fillRect(x1, 0, x2 - x1, h, color)

            # Draw segment text if there's enough space
            text_w = x2 - x1
            if text_w > 30:
                painter.setPen(Qt.white)
                font = painter.font()
                font.setPointSize(8)
                painter.setFont(font)
                painter.drawText(
                    QtCore.QRect(x1 + 2, 0, text_w - 4, h),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    seg.text[:20],
                )

        painter.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            frame = int(event.x() / self.width() * self._total_frames)
            frame = max(0, min(frame, self._total_frames - 1))
            self.clicked.emit(frame)


class TimelineWidget(QtWidgets.QWidget):
    """Timeline slider with segment visualization and frame navigation."""

    frame_changed = QtCore.pyqtSignal(int)

    _total_frames: int
    _slider: QtWidgets.QSlider
    _segment_bar: _SegmentBar
    _frame_label: QtWidgets.QLabel
    _prev_btn: QtWidgets.QPushButton
    _next_btn: QtWidgets.QPushButton

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._total_frames = 1
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Segment bar
        self._segment_bar = _SegmentBar()
        self._segment_bar.clicked.connect(self._on_bar_clicked)
        layout.addWidget(self._segment_bar)

        # Slider row
        slider_row = QtWidgets.QHBoxLayout()
        slider_row.setSpacing(4)

        self._prev_btn = QtWidgets.QPushButton("<")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.clicked.connect(self._prev_frame)

        self._slider = QtWidgets.QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.valueChanged.connect(self._on_slider_changed)

        self._next_btn = QtWidgets.QPushButton(">")
        self._next_btn.setFixedWidth(30)
        self._next_btn.clicked.connect(self._next_frame)

        self._frame_label = QtWidgets.QLabel("0 / 0")
        self._frame_label.setFixedWidth(100)
        self._frame_label.setAlignment(Qt.AlignCenter)

        slider_row.addWidget(self._prev_btn)
        slider_row.addWidget(self._slider, 1)
        slider_row.addWidget(self._next_btn)
        slider_row.addWidget(self._frame_label)

        layout.addLayout(slider_row)

    def set_range(self, total_frames: int) -> None:
        self._total_frames = total_frames
        self._slider.setMaximum(max(total_frames - 1, 0))
        self._slider.setValue(0)
        self._update_label()

    def set_segments(self, segments: list[Segment]) -> None:
        self._segment_bar.set_data(self._total_frames, segments)

    def set_frame(self, frame_idx: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(frame_idx)
        self._slider.blockSignals(False)
        self._update_label()

    def current_frame(self) -> int:
        return self._slider.value()

    def _on_slider_changed(self, value: int) -> None:
        self._update_label()
        self.frame_changed.emit(value)

    def _on_bar_clicked(self, frame: int) -> None:
        self._slider.setValue(frame)

    def _prev_frame(self) -> None:
        self._slider.setValue(max(0, self._slider.value() - 1))

    def _next_frame(self) -> None:
        self._slider.setValue(
            min(self._slider.maximum(), self._slider.value() + 1)
        )

    def _update_label(self) -> None:
        self._frame_label.setText(
            f"{self._slider.value()} / {self._total_frames - 1}"
        )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key_Left:
            self._prev_frame()
        elif event.key() == Qt.Key_Right:
            self._next_frame()
        else:
            super().keyPressEvent(event)
