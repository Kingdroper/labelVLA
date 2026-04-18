from __future__ import annotations

import matplotlib
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from numpy.typing import NDArray
from PyQt5 import QtCore
from PyQt5 import QtWidgets

from labelme.lerobot.segment import Segment

matplotlib.use("Qt5Agg")

# Distinct colors for segment bands (matching timeline)
_SEGMENT_COLORS: list[tuple[float, float, float, float]] = [
    (0.298, 0.686, 0.314, 0.25),
    (0.129, 0.588, 0.953, 0.25),
    (1.0, 0.596, 0.0, 0.25),
    (0.612, 0.153, 0.690, 0.25),
    (0.957, 0.263, 0.212, 0.25),
    (0.0, 0.737, 0.831, 0.25),
    (1.0, 0.922, 0.231, 0.25),
    (0.475, 0.333, 0.282, 0.25),
]


class JointPlotWidget(QtWidgets.QWidget):
    """Matplotlib widget showing joint angle curves with cursor and segment bands."""

    frame_selected = QtCore.pyqtSignal(int)

    _canvas: FigureCanvasQTAgg
    _figure: Figure
    _states: NDArray[np.float32] | None
    _joint_names: list[str]
    _joint_visible: list[bool]
    _segments: list[Segment]
    _current_frame: int
    _cursor_line: object | None
    _checkboxes: list[QtWidgets.QCheckBox]
    _checkbox_container: QtWidgets.QWidget

    def __init__(
        self,
        joint_names: list[str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._states = None
        self._joint_names = joint_names or []
        self._joint_visible = [True] * len(self._joint_names)
        self._segments = []
        self._current_frame = 0
        self._cursor_line = None
        self._checkboxes = []

        self._figure = Figure(figsize=(8, 3), dpi=80)
        self._figure.set_tight_layout(True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.mpl_connect("button_press_event", self._on_click)

        # Main layout: plot on top, joint checkboxes below
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._canvas, 1)

        # Checkbox panel (collapsible)
        toggle_btn = QtWidgets.QPushButton("Joints ▼")
        toggle_btn.setFixedHeight(20)
        toggle_btn.setStyleSheet("font-size: 10px; text-align: left; padding-left: 4px;")
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(False)
        toggle_btn.toggled.connect(self._toggle_checkbox_panel)
        layout.addWidget(toggle_btn)
        self._toggle_btn = toggle_btn

        self._checkbox_container = QtWidgets.QWidget()
        self._checkbox_container.setVisible(False)
        self._checkbox_layout = QtWidgets.QHBoxLayout(self._checkbox_container)
        self._checkbox_layout.setContentsMargins(4, 0, 4, 0)
        self._checkbox_layout.setSpacing(2)

        # Select all / none buttons
        all_btn = QtWidgets.QPushButton("All")
        all_btn.setFixedSize(36, 20)
        all_btn.setStyleSheet("font-size: 9px;")
        all_btn.clicked.connect(self._select_all)
        none_btn = QtWidgets.QPushButton("None")
        none_btn.setFixedSize(40, 20)
        none_btn.setStyleSheet("font-size: 9px;")
        none_btn.clicked.connect(self._select_none)
        self._checkbox_layout.addWidget(all_btn)
        self._checkbox_layout.addWidget(none_btn)

        # Scroll area for checkboxes (can be many joints)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(60)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self._cb_inner = QtWidgets.QWidget()
        self._cb_flow = _FlowLayout(self._cb_inner)
        self._cb_flow.setContentsMargins(0, 0, 0, 0)
        self._cb_flow.setSpacing(4)
        scroll.setWidget(self._cb_inner)

        self._checkbox_layout.addWidget(scroll, 1)
        layout.addWidget(self._checkbox_container)

        self._build_checkboxes()

    def _toggle_checkbox_panel(self, checked: bool) -> None:
        self._checkbox_container.setVisible(checked)
        self._toggle_btn.setText("Joints ▲" if checked else "Joints ▼")

    def _build_checkboxes(self) -> None:
        # Clear existing
        for cb in self._checkboxes:
            self._cb_flow.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        for i, name in enumerate(self._joint_names):
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(self._joint_visible[i] if i < len(self._joint_visible) else True)
            cb.setStyleSheet("font-size: 9px;")
            cb.toggled.connect(self._on_checkbox_toggled)
            self._cb_flow.addWidget(cb)
            self._checkboxes.append(cb)

    def _on_checkbox_toggled(self) -> None:
        self._joint_visible = [cb.isChecked() for cb in self._checkboxes]
        self._redraw()

    def _select_all(self) -> None:
        for cb in self._checkboxes:
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._joint_visible = [True] * len(self._checkboxes)
        self._redraw()

    def _select_none(self) -> None:
        for cb in self._checkboxes:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._joint_visible = [False] * len(self._checkboxes)
        self._redraw()

    def set_data(
        self,
        states: NDArray[np.float32],
        joint_names: list[str] | None = None,
    ) -> None:
        """Set joint state data. states shape: (num_frames, num_joints)."""
        self._states = states
        if joint_names is not None:
            self._joint_names = joint_names
            self._joint_visible = [True] * len(joint_names)
            self._build_checkboxes()
        self._redraw()

    def set_segments(self, segments: list[Segment]) -> None:
        self._segments = segments
        self._redraw()

    def set_current_frame(self, frame_idx: int) -> None:
        self._current_frame = frame_idx
        self._update_cursor()

    def _redraw(self) -> None:
        self._figure.clear()
        if self._states is None or len(self._states) == 0:
            self._canvas.draw()
            return

        ax = self._figure.add_subplot(111)
        num_frames, num_joints = self._states.shape
        x = np.arange(num_frames)

        # Determine visible joints for y-axis range
        visible_indices = [
            j for j in range(num_joints)
            if j < len(self._joint_visible) and self._joint_visible[j]
        ]

        if visible_indices:
            visible_data = self._states[:, visible_indices]
            y_min = float(visible_data.min())
            y_max = float(visible_data.max())
        else:
            y_min = float(self._states.min())
            y_max = float(self._states.max())
        margin = (y_max - y_min) * 0.05 if y_max > y_min else 0.1

        # Draw segment bands
        for i, seg in enumerate(self._segments):
            color = _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)]
            ax.axvspan(seg.start_frame, seg.end_frame, color=color)

        # Plot only visible joints
        for j in range(num_joints):
            if j < len(self._joint_visible) and not self._joint_visible[j]:
                continue
            name = self._joint_names[j] if j < len(self._joint_names) else f"joint_{j}"
            ax.plot(x, self._states[:, j], linewidth=0.8, label=name)

        # Cursor
        self._cursor_line = ax.axvline(
            self._current_frame, color="red", linewidth=1.5, linestyle="--"
        )

        ax.set_xlim(0, num_frames - 1)
        ax.set_ylim(y_min - margin, y_max + margin)
        ax.set_xlabel("Frame")
        ax.set_ylabel("Joint Value")

        # Legend
        num_visible = len(visible_indices)
        if 0 < num_visible <= 14:
            ax.legend(
                fontsize=6,
                loc="upper right",
                ncol=min(num_visible, 4),
                framealpha=0.7,
            )

        self._canvas.draw()

    def _update_cursor(self) -> None:
        if self._cursor_line is not None:
            self._cursor_line.set_xdata([self._current_frame, self._current_frame])
            self._canvas.draw_idle()

    def _on_click(self, event: object) -> None:
        if (
            self._states is not None
            and hasattr(event, "xdata")
            and event.xdata is not None  # type: ignore[union-attr]
        ):
            frame = int(round(event.xdata))  # type: ignore[union-attr]
            frame = max(0, min(frame, len(self._states) - 1))
            self.frame_selected.emit(frame)


class _FlowLayout(QtWidgets.QLayout):
    """Simple flow layout that wraps widgets to the next row."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self._spacing = 4

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing

    def spacing(self) -> int:
        return self._spacing

    def sizeHint(self) -> QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:
        size = QtCore.QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QtCore.QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def setGeometry(self, rect: QtCore.QRect) -> None:
        super().setGeometry(rect)
        if not self._items:
            return
        x = rect.x() + self.contentsMargins().left()
        y = rect.y() + self.contentsMargins().top()
        row_height = 0
        right_edge = rect.right() - self.contentsMargins().right()

        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > right_edge and row_height > 0:
                x = rect.x() + self.contentsMargins().left()
                y += row_height + self._spacing
                row_height = 0
            item.setGeometry(QtCore.QRect(x, y, w, h))
            x += w + self._spacing
            row_height = max(row_height, h)
