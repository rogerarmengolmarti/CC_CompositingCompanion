# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - backDropUI.py
# ////////////////////////////////////////////////////////////////////

import os
import sys
import platform
import json
#from backDropFunctions import randomColor

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

        self.resize(400, 500)

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

        # ---- Name input row ----
        input_row = QtWidgets.QHBoxLayout()
        input_row.addWidget(QtWidgets.QLabel("Name:"))

        self.name_field = QtWidgets.QLineEdit()
        self.name_field.setPlaceholderText("Enter backdrop name...")

        input_row.addWidget(self.name_field)
        root_layout.addLayout(input_row)

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

        self.color_icn = QtWidgets.QPushButton()
        self.color_icn.setEnabled(False)
        self.iconColor = randomColor()
        self.color_icn.setStyleSheet(f"""
            QPushButton:disabled {{
                background-color: {self.iconColor};
                color: #ffffff;
                border: 2px solid {self.iconColor};
                border-radius: 4px;      
                font-weight: bold;
                font-size: 14px;
            }}
        """)

        format_layout.addWidget(self.center_check)
        format_layout.addWidget(self.bold_check)
        format_layout.addWidget(self.italics_check)
        format_layout.addWidget(self.bookmark_check)
        format_layout.addWidget(self.filled_check)
        format_layout.addWidget(self.size_spb)
        format_layout.addWidget(self.size_text)
        format_layout.addWidget(self.color_icn)

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
        self.iconColor = preset.get("color", "#3a3a3a")
        self._on_run()

    # ------------------------------------------------------------------
    # Slots / Logic
    # ------------------------------------------------------------------

    def _on_run(self):
        
        uiValue_name = self.name_field.text()
        uiValue_center = self.center_check.isChecked()
        uiValue_bold = self.bold_check.isChecked()
        uiValue_italics = self.italics_check.isChecked()
        uiValue_bookmark = self.bookmark_check.isChecked()
        uivalue_filled = self.filled_check.isChecked()
        uiValue_size = self.size_spb.value()
        uiValue_color = self.iconColor
        
        uiData = {
            "name": uiValue_name,
            "center": uiValue_center,
            "bold": uiValue_bold,
            "italics": uiValue_italics,
            "bookmark": uiValue_bookmark,
            "filled": uivalue_filled,
            "size": uiValue_size,
            "color": uiValue_color
        }

        backDropFunctions.createBackDrop(uiData)
        self.window().close()


    def _on_reset(self):
        self.name_field.clear()
        self.mode_combo.setCurrentIndex(0)
        self.enable_check.setChecked(False)
        self.log_output.clear()

    def log(self, message: str):
        """Append a line to the log area and echo to Nuke's script editor."""
        self.log_output.appendPlainText(message)
        print(f"[MyPanel] {message}")



# ---------------------------------------------------------------------------
# Floating dialog
# ---------------------------------------------------------------------------

def show_floating():
    """Open window as floating."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("[CC] - Compositing Companion")
    dialog.setMinimumWidth(500)
    
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(Window())
    dialog.exec_()

