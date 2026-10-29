# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - backDropUI.py
# ////////////////////////////////////////////////////////////////////

import os
import sys
import math
import platform
import json

sys.dont_write_bytecode = True  # Avoid writing .pyc files


try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui # pyright: ignore[reportMissingImports]


import nuke
import backDropFunctions

# ----- Directory paths -----
PRESETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backdrop_presets.json')

# ----- Tool Variables -----
PRESET_COLUMNS = 3  # buttons per row in the preset grid


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def randomColor():
    import colorsys
    import random
    h = random.random()
    s = random.uniform(0.25, 0.65)
    l = random.uniform(0.25, 0.35)

    # HLS to RGB
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))

def _refresh_icon(size=32, color="#dddddd"):
    """Draw a 'two rotating arrows' icon (refresh / random) as a QIcon."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)

    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(size * 0.09)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    p.setPen(pen)

    margin = size * 0.2
    rect = QtCore.QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    cx, cy = rect.center().x(), rect.center().y()
    radius = rect.width() / 2.0
    head = size * 0.2

    span = 140
    for start in (20, 200):  # two arcs, opposite sides
        p.drawArc(rect, int(start * 16), int(span * 16))

        # Arrowhead at the end of the arc (counter-clockwise direction)
        a = math.radians(start + span)
        tip = QtCore.QPointF(cx + radius * math.cos(a), cy - radius * math.sin(a))
        dx, dy = -math.sin(a), -math.cos(a)  # tangent direction in screen coords

        for off in (35, -35):
            o = math.radians(off)
            bx, by = -dx, -dy  # points backwards from the tip
            rx = bx * math.cos(o) - by * math.sin(o)
            ry = bx * math.sin(o) + by * math.cos(o)
            p.drawLine(tip, QtCore.QPointF(tip.x() + rx * head, tip.y() + ry * head))

    p.end()
    return QtGui.QIcon(pm)

def _preset_button_style(hex_color: str):
    """Return a stylesheet matching the colour-swatch button style, with white label."""
    return f"""
        QPushButton {{
            background-color: {hex_color};
            color: #ffffff;
            border: 2px solid {hex_color};
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
            padding: 4px 8px;
        }}
        QPushButton:hover {{
            border: 2px solid #ffffff;
        }}
        QPushButton:pressed {{
            opacity: 0.8;
        }}
    """

def _swatch_style(hex_color: str):
    """Stylesheet for the clickable colour swatch button."""
    return f"""
        QPushButton {{
            background-color: {hex_color};
            border: 2px solid {hex_color};
            border-radius: 4px;
        }}
        QPushButton:hover {{
            border: 2px solid #ffffff;
        }}
    """

def _load_presets():
    """Load presets from JSON. Returns [] on any error."""
    if not os.path.exists(PRESETS_PATH):
        print(f"[CC] Presets file not found: {PRESETS_PATH}")
        return []
    try:
        with open(PRESETS_PATH, "r") as f:
            data = json.load(f)
        return data.get("presets", [])
    except Exception as e:
        print(f"[CC] Failed to load presets: {e}")
        return []


# ---------------------------------------------------------------------------
# Main Panel Widget
# ---------------------------------------------------------------------------

class Window(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(Window, self).__init__(parent)
        self.setWindowTitle("Backdrop Creator - Compositing Companion")

        self.resize(360, 320)

        self.iconColor = randomColor()

        self._build_ui()
        self._connect_signals()

    def _on_enter_pressed(self):
        name = self.name_field.text().strip()
        if not name:
            return

        # Check if name matches an existing preset
        presets = _load_presets()
        match = next((p for p in presets if p['name'].lower() == name.lower()), None)

        if match:
            self._apply_preset(match)
        else:
            self._on_run()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # ---- Header label ----
        self.header_label = QtWidgets.QLabel("Backdrop Creator")
        self.header_label.setStyleSheet("font-weight: bold; font-size: 20px;") # disabeled:  color: #33cc70;

        root_layout.addWidget(self.header_label)
        root_layout.addWidget(self._make_separator())

        # ---- Name + color row ----
        input_row = QtWidgets.QHBoxLayout()
        input_row.addWidget(QtWidgets.QLabel("Name:"))

        self.name_field = QtWidgets.QLineEdit()
        self.name_field.setPlaceholderText("Enter backdrop name...")
        input_row.addWidget(self.name_field, 1)

        # Colour swatch = button that opens the picker
        self.color_icn = QtWidgets.QPushButton()
        self.color_icn.setFixedSize(32, 24)
        self.color_icn.setCursor(QtCore.Qt.PointingHandCursor)
        self.color_icn.setToolTip("Click to pick a colour")

        # Random colour button with two rotating arrows icon
        self.random_color_btn = QtWidgets.QPushButton()
        self.random_color_btn.setIcon(_refresh_icon(32))
        self.random_color_btn.setIconSize(QtCore.QSize(18, 18))
        self.random_color_btn.setFixedSize(28, 24)
        self.random_color_btn.setToolTip("Random colour")

        input_row.addWidget(self.color_icn)
        input_row.addWidget(self.random_color_btn)
        root_layout.addLayout(input_row)

        self._set_color(self.iconColor)

        # ---- Format Layout ----
        format_layout = QtWidgets.QHBoxLayout()

        self.center_check = QtWidgets.QCheckBox("Center")
        self.center_check.setChecked(True)

        self.bold_check = QtWidgets.QCheckBox("Bold")
        self.bold_check.setChecked(True)

        self.italics_check = QtWidgets.QCheckBox("Italics")

        self.bookmark_check = QtWidgets.QCheckBox("Bookmark")
        self.bookmark_check.setChecked(True)

        self.filled_check = QtWidgets.QCheckBox("Filled")
        self.filled_check.setChecked(True)

        self.size_spb = QtWidgets.QSpinBox()
        self.size_spb.setRange(0, 200)
        self.size_spb.setSingleStep(5)
        self.size_spb.setValue(25)

        self.size_text = QtWidgets.QLabel("Size")

        format_layout.addWidget(self.center_check)
        format_layout.addWidget(self.bold_check)
        format_layout.addWidget(self.italics_check)
        format_layout.addWidget(self.bookmark_check)
        format_layout.addWidget(self.filled_check)
        format_layout.addWidget(self.size_spb)
        format_layout.addWidget(self.size_text)

        root_layout.addLayout(format_layout)

        root_layout.addWidget(self._make_separator())

        # ---- Action buttons ----
        btn_row = QtWidgets.QHBoxLayout()
        self.create_btn = QtWidgets.QPushButton("Create")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        btn_row.addWidget(self.create_btn)
        btn_row.addWidget(self.cancel_btn)
        root_layout.addLayout(btn_row)

        root_layout.addWidget(self._make_separator())

        # ---- Presets ----
        presets_header_row = QtWidgets.QHBoxLayout()
        presets_label = QtWidgets.QLabel("Presets")
        presets_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.reload_btn = QtWidgets.QPushButton("Reload")
        self.reload_btn.setFixedWidth(50)
        self.reload_btn.setToolTip("Reload presets from JSON")
        presets_header_row.addWidget(presets_label)
        presets_header_row.addStretch()
        presets_header_row.addWidget(self.reload_btn)
        root_layout.addLayout(presets_header_row)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        self.preset_container = QtWidgets.QWidget()
        self.preset_grid = QtWidgets.QGridLayout(self.preset_container)
        self.preset_grid.setSpacing(4)

        scroll.setWidget(self.preset_container)
        root_layout.addWidget(scroll)

        self._populate_presets()

    def _make_separator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.name_field.returnPressed.connect(self._on_enter_pressed)
        self.create_btn.clicked.connect(self._on_run)
        self.cancel_btn.clicked.connect(self._on_reset)
        self.random_color_btn.clicked.connect(self._on_random_color)
        self.color_icn.clicked.connect(self._on_pick_color)
        self.reload_btn.clicked.connect(self._populate_presets)

    # ------------------------------------------------------------------
    # Color handling
    # ------------------------------------------------------------------

    def _set_color(self, hex_color: str):
        """Single entry point to change the current colour and refresh the swatch."""
        self.iconColor = hex_color
        self.color_icn.setStyleSheet(_swatch_style(hex_color))
        self.color_icn.setToolTip(f"{hex_color.upper()} - click to pick a colour")

    def _on_random_color(self):
        self._set_color(randomColor())

    def _on_pick_color(self):
        initial = QtGui.QColor(self.iconColor)
        color = QtWidgets.QColorDialog.getColor(initial, self, "Pick backdrop colour")
        if color.isValid():
            self._set_color(color.name())  # '#rrggbb'

    # ------------------------------------------------------------------
    # Preset loader
    # ------------------------------------------------------------------

    def _populate_presets(self):
        """Clear the grid and rebuild from JSON."""
        # Remove existing widgets
        while self.preset_grid.count():
            item = self.preset_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        presets = _load_presets()

        if not presets:
            empty_label = QtWidgets.QLabel("No presets found.")
            empty_label.setStyleSheet("color: #888888; font-style: italic;")
            self.preset_grid.addWidget(empty_label, 0, 0)
            return

        for idx, preset in enumerate(presets):
            row = idx // PRESET_COLUMNS
            col = idx % PRESET_COLUMNS

            btn = QtWidgets.QPushButton(preset["name"])
            btn.setStyleSheet(_preset_button_style(preset.get("color", "#3a3a3a")))
            btn.setMinimumHeight(32)

            # Capture preset data in the closure
            btn.clicked.connect(lambda checked=False, p=preset: self._apply_preset(p))

            self.preset_grid.addWidget(btn, row, col)

    def _apply_preset(self, preset: dict):
        """Load a preset's values into the form fields."""
        self.name_field.setText(preset.get("name", ""))
        self.bold_check.setChecked(preset.get("bold", True))
        self.italics_check.setChecked(preset.get("italics", False))
        self.center_check.setChecked(preset.get("center", True))
        self.bookmark_check.setChecked(preset.get("bookmark", True))
        self.filled_check.setChecked(preset.get("filled", True))
        self.size_spb.setValue(preset.get("size", 25))
        self._set_color(preset.get("color", "#3a3a3a"))
        self._on_run()

    # ------------------------------------------------------------------
    # Slots / Logic
    # ------------------------------------------------------------------

    def _on_run(self):

        uiData = {
            "name": self.name_field.text(),
            "center": self.center_check.isChecked(),
            "bold": self.bold_check.isChecked(),
            "italics": self.italics_check.isChecked(),
            "bookmark": self.bookmark_check.isChecked(),
            "filled": self.filled_check.isChecked(),
            "size": self.size_spb.value(),
            "color": self.iconColor
        }

        backDropFunctions.createBackDrop(uiData)
        self.window().close()

    def _on_reset(self):
        """Reset the form to defaults."""
        self.name_field.clear()
        self.center_check.setChecked(True)
        self.bold_check.setChecked(True)
        self.italics_check.setChecked(False)
        self.bookmark_check.setChecked(True)
        self.filled_check.setChecked(True)
        self.size_spb.setValue(25)
        self._set_color(randomColor())


# ---------------------------------------------------------------------------
# Floating dialog
# ---------------------------------------------------------------------------

def show_floating():
    """Open window as floating."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("[CC] - Compositing Companion")
    dialog.setMinimumWidth(360)

    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(Window())
    dialog.exec_()