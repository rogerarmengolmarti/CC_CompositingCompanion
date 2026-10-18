# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - nukeTreeScreenshot.py
# ////////////////////////////////////////////////////////////////////

# Based on the code by herronelou - nuke_dag_capture

import getpass
import html
import json
import logging
import os
import re
import time
from collections import namedtuple
from datetime import datetime
from math import ceil

import nuke

if nuke.NUKE_VERSION_MAJOR < 16:
    from PySide2 import QtWidgets, QtOpenGL, QtGui, QtCore
    DAGType = QtOpenGL.QGLWidget

    def is_dag_widget(widget):
        return isinstance(widget, QtOpenGL.QGLWidget)
else:
    from PySide6 import QtWidgets, QtGui, QtCore
    DAGType = QtWidgets.QWidget

    def is_dag_widget(widget):
        return widget.objectName() == 'DAG'


LOG = logging.getLogger("cc.dag_capture")

SETTINGS_ORG = "CompositingCompanion"
SETTINGS_APP = "DagCapture"

FORMATS = {"PNG": ".png", "JPG": ".jpg"}
MAX_SIDE_PX = 65000          # JPEG hard limit is 65535
WARN_MEGAPIXELS = 100
OVERLAY_WIDTH = 150
MIN_OVERLAY_STRIP = OVERLAY_WIDTH + 20

CAPTURE_BG = "#2b2b2b"
BAR_BG = "#1f1f1f"
BAR_FG = "#d9d9d9"
BAR_ACCENT = "#e8a33d"
COLOR_ERROR = "#e0624d"
COLOR_WARN = "#e8a33d"

TOKEN_HELP = "Tokens: {project} {version} {script} {date} {time} {user} {nodes} {zoom}"

DEFAULTS = {
    "folder": "",                 # empty = <script dir>/screenshot
    "zoom": 0.2,
    "margin": 100,
    "crop_right": 200,
    "delay": 0.0,
    "deselect": True,
    "format": "PNG",
    "quality": 95,
    "overwrite": False,
    "open_folder": False,
    "to_clipboard": False,
    "header_on": True,
    "header_left": "{project}",
    "header_right": "{version}",
    "footer_on": True,
    "footer_left": "{date} {time}  |  {user}",
    "footer_right": "{nodes} nodes  |  zoom {zoom}",
    "font_px": 50,
}

Layout = namedtuple(
    "Layout", "left top width height tiles_x tiles_y cap_w cap_h dag_w dag_h"
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def get_dag() -> DAGType:
    """Retrieve the DAG widget"""
    stack = list(QtWidgets.QApplication.topLevelWidgets())
    while stack:
        widget = stack.pop()
        if widget.objectName() == 'DAG.1':
            for c in widget.children():
                if is_dag_widget(c):
                    return c

        stack.extend(c for c in widget.children() if c.isWidgetType())
    return None


def grab_dag(dag: DAGType) -> QtGui.QImage:
    """Grab the current DAG view and return it as a QImage at logical size"""
    width, height = dag.width(), dag.height()
    try:
        # Nuke < 16: updateGL is needed, otherwise grabFrameBuffer returns a stale buffer
        dag.updateGL()
        img = dag.grabFrameBuffer()
    except AttributeError:
        # Nuke 16+: no GL widget access, fall back to a screen grab of the DAG area
        QtWidgets.QApplication.processEvents()
        global_pos = dag.mapToGlobal(QtCore.QPoint(0, 0))
        screen = QtGui.QGuiApplication.screenAt(global_pos) or QtGui.QGuiApplication.primaryScreen()
        local = global_pos - screen.geometry().topLeft()
        img = screen.grabWindow(0, local.x(), local.y(), width, height).toImage()

    # HiDPI: the grab can be larger than the widget, bring it back to logical pixels
    if img.width() != width or img.height() != height:
        img = img.scaled(width, height, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    return img


def script_info() -> dict:
    """Project / version / folder info derived from the current Nuke script name"""
    path = nuke.root().name()
    if path in ("", "Root"):
        return {"dir": "", "name": "untitled", "stem": "untitled",
                "project": "Untitled", "version": ""}

    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    project, version = stem, ""
    matches = list(re.finditer(r"[._-]?[vV]\d+", stem))
    if matches:
        last = matches[-1]
        version = last.group(0).lstrip("._-")
        project = (stem[:last.start()] + stem[last.end():]).strip("._-") or stem
    return {"dir": os.path.dirname(path), "name": name, "stem": stem,
            "project": project, "version": version}


def nodes_bbox(selected_only: bool):
    """Return ((min_x, min_y, max_x, max_y), node_count) or (None, 0)"""
    nodes = nuke.selectedNodes() if selected_only else nuke.allNodes()
    if not nodes:
        return None, 0
    min_x = min(n.xpos() for n in nodes)
    min_y = min(n.ypos() for n in nodes)
    max_x = max(n.xpos() + n.screenWidth() for n in nodes)
    max_y = max(n.ypos() + n.screenHeight() for n in nodes)
    return (min_x, min_y, max_x, max_y), len(nodes)


def compute_layout(bbox, zoom, margin, dag_w, dag_h, crop_right):
    """Image size + tile grid. Shared by the UI preview and the capture thread."""
    cap_w = dag_w - crop_right
    cap_h = dag_h
    if bbox is None or cap_w <= 0 or cap_h <= 0:
        return None
    min_x, min_y, max_x, max_y = bbox
    width = int(ceil((max_x - min_x) * zoom + margin * 2))
    height = int(ceil((max_y - min_y) * zoom + margin * 2))
    return Layout(
        left=min_x - margin / float(zoom),
        top=min_y - margin / float(zoom),
        width=width,
        height=height,
        tiles_x=int(ceil(width / float(cap_w))),
        tiles_y=int(ceil(height / float(cap_h))),
        cap_w=cap_w, cap_h=cap_h, dag_w=dag_w, dag_h=dag_h,
    )


def unique_path(path: str) -> str:
    """file.png -> file_001.png -> file_002.png ... if the file already exists"""
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = "{}_{:03d}{}".format(base, n, ext)
        n += 1
    return path


class _SafeDict(dict):
    def __missing__(self, key):
        return "{%s}" % key


def format_tokens(template: str, tokens: dict) -> str:
    """str.format that leaves unknown tokens / stray braces untouched"""
    try:
        return template.format_map(_SafeDict(tokens))
    except (ValueError, IndexError, KeyError, AttributeError):
        return template


# --------------------------------------------------------------------------------------
# Watermark
# --------------------------------------------------------------------------------------
def render_bar(width, height, left_text, right_text, font_px, accent_bottom):
    """One watermark bar: left text (elided if needed) + right-aligned text."""
    img = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(BAR_BG))

    painter = QtGui.QPainter(img)
    font = QtGui.QFont()
    font.setPixelSize(font_px)
    painter.setFont(font)
    painter.setPen(QtGui.QColor(BAR_FG))
    fm = QtGui.QFontMetrics(font)

    pad = int(font_px * 0.8)
    baseline = (height - fm.height()) // 2 + fm.ascent()
    right_w = fm.horizontalAdvance(right_text) if right_text else 0
    if right_text:
        painter.drawText(max(width - pad - right_w, pad), baseline, right_text)

    avail = width - pad * 2 - (right_w + pad if right_text else 0)
    if left_text and avail > 0:
        painter.drawText(pad, baseline, fm.elidedText(left_text, QtCore.Qt.ElideRight, avail))

    line_y = height - 2 if accent_bottom else 0
    painter.fillRect(0, line_y, width, 2, QtGui.QColor(BAR_ACCENT))
    painter.end()
    return img


def add_watermark(image, header, footer, font_px):
    """Extend the image with a header and/or footer bar. header/footer: (left, right) or None."""
    bar_h = int(font_px * 2.2)
    top_h = bar_h if header else 0
    bottom_h = bar_h if footer else 0
    if not top_h and not bottom_h:
        return image

    out = QtGui.QImage(image.width(), image.height() + top_h + bottom_h, QtGui.QImage.Format_RGB32)
    painter = QtGui.QPainter(out)
    if header:
        painter.drawImage(0, 0, render_bar(image.width(), bar_h, header[0], header[1], font_px, True))
    painter.drawImage(0, top_h, image)
    if footer:
        painter.drawImage(0, top_h + image.height(),
                          render_bar(image.width(), bar_h, footer[0], footer[1], font_px, False))
    painter.end()
    return out


# --------------------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------------------
class CollapsibleSection(QtWidgets.QWidget):
    """Arrow toggle + collapsible body"""

    def __init__(self, title: str, parent=None) -> None:
        super(CollapsibleSection, self).__init__(parent)
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.RightArrow)
        self.toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.toggle.toggled.connect(self._on_toggled)

        self.body = QtWidgets.QWidget()
        self.body.setVisible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)

    def set_body_layout(self, layout) -> None:
        self.body.setLayout(layout)

    def _on_toggled(self, checked: bool) -> None:
        self.toggle.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
        self.body.setVisible(checked)


class ProgressOverlay(QtWidgets.QWidget):
    """Tiny always-on-top progress + cancel window shown while capturing"""
    cancel_requested = QtCore.Signal()

    def __init__(self) -> None:
        flags = QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
        super(ProgressOverlay, self).__init__(None, flags)
        self.setObjectName("ccCaptureOverlay")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet("#ccCaptureOverlay { background: #2b2b2b; border: 1px solid #666; }")
        self.setFixedWidth(OVERLAY_WIDTH)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.label = QtWidgets.QLabel("Capturing...")
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addWidget(self.cancel_btn)

    def set_progress(self, done: int, total: int) -> None:
        self.label.setText("Tile {}/{}".format(done, total))
        self.bar.setValue(int(100.0 * done / max(total, 1)))

    def _on_cancel(self) -> None:
        self.label.setText("Cancelling...")
        self.cancel_btn.setEnabled(False)
        self.cancel_requested.emit()


# --------------------------------------------------------------------------------------
# Capture thread
# --------------------------------------------------------------------------------------
class DagCapture(QtCore.QThread):
    """Walks the DAG tile by tile and stitches the grabs into one QImage"""
    progress = QtCore.Signal(int, int)

    def __init__(self, dag: DAGType) -> None:
        super(DagCapture, self).__init__()
        self.dag = dag
        self.plan = None          # Layout
        self.zoom = 1.0
        self.delay = 0.0
        self.restore = None       # (zoom, center) to restore afterwards, read on the main thread
        self.image = None
        self.error = ""
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        self._cancel = False
        self.image = None
        self.error = ""
        try:
            self.image = self._stitch()
        except Exception as exc:  # noqa - report to the UI, never kill the thread silently
            LOG.exception("DAG capture failed")
            self.error = str(exc) or exc.__class__.__name__
        finally:
            if self.restore:
                nuke.executeInMainThreadWithResult(nuke.zoom, self.restore)

    def _stitch(self):
        plan, zoom = self.plan, self.zoom

        image = QtGui.QImage(plan.width, plan.height, QtGui.QImage.Format_RGB32)
        if image.isNull():
            raise MemoryError("Couldn't allocate a {}x{} image, lower the zoom or margins".format(
                plan.width, plan.height))
        image.fill(QtGui.QColor(CAPTURE_BG))

        total = plan.tiles_x * plan.tiles_y
        done = 0
        time.sleep(0.2)  # let the UI settle after the panel was hidden

        painter = QtGui.QPainter(image)
        try:
            for tile_x in range(plan.tiles_x):
                center_x = plan.left + (tile_x * plan.cap_w + plan.dag_w / 2.0) / zoom
                for tile_y in range(plan.tiles_y):
                    if self._cancel:
                        return None
                    center_y = plan.top + (tile_y * plan.cap_h + plan.dag_h / 2.0) / zoom

                    nuke.executeInMainThreadWithResult(nuke.zoom, (zoom, (center_x, center_y)))
                    time.sleep(self.delay)
                    tile = nuke.executeInMainThreadWithResult(grab_dag, (self.dag,))

                    # Only paste the cropped area (without the minimap strip on the right)
                    painter.drawImage(tile_x * plan.cap_w, tile_y * plan.cap_h, tile,
                                      0, 0, plan.cap_w, plan.cap_h)
                    done += 1
                    self.progress.emit(done, total)
        finally:
            painter.end()
        return image


# --------------------------------------------------------------------------------------
# Main panel
# --------------------------------------------------------------------------------------
class DagCapturePanel(QtWidgets.QDialog):
    """UI Panel for DAG capture options"""

    def __init__(self) -> None:
        super(DagCapturePanel, self).__init__(QtWidgets.QApplication.activeWindow())

        self.dag = get_dag()
        if not self.dag:
            raise RuntimeError("Couldn't get DAG widget")

        self.script = script_info()
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.bbox = None
        self.node_count = 0
        self.selection = []
        self.overlay = None
        self.pending = {}
        self._loading = True

        self.capture_thread = DagCapture(self.dag)
        self.capture_thread.progress.connect(self.on_progress)
        self.capture_thread.finished.connect(self.on_thread_finished)

        self._build_ui()
        self._apply_config(self._read_config())
        self.project_edit.setText(self.script["project"])
        self.version_edit.setText(self.script["version"])
        self.folder_edit.setPlaceholderText(self.auto_dir())
        self._loading = False
        self.inspect_dag()

    # ---------------------------------------------------------------- UI
    def _form(self):
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        return form

    def _build_ui(self) -> None:
        self.setObjectName(PANEL_NAME)
        self.setWindowTitle("DAG Capture")
        self.setMinimumWidth(560)
        root = QtWidgets.QVBoxLayout(self)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._tab_capture(), "Capture")
        tabs.addTab(self._tab_watermark(), "Watermark")
        tabs.addTab(self._tab_output(), "Output")
        root.addWidget(tabs)

        # Summary
        self.info = QtWidgets.QLabel()
        self.info.setTextFormat(QtCore.Qt.RichText)
        self.info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.info.setWordWrap(True)
        info_box = QtWidgets.QFrame()
        info_box.setFrameStyle(QtWidgets.QFrame.StyledPanel)
        QtWidgets.QVBoxLayout(info_box).addWidget(self.info)
        root.addWidget(info_box)

        # Status (last result)
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.RichText)
        self.status.setOpenExternalLinks(True)
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # Buttons
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        self.capture_btn = QtWidgets.QPushButton("Capture")
        self.capture_btn.setDefault(True)
        self.capture_btn.clicked.connect(self.do_capture)
        buttons.addWidget(close_btn)
        buttons.addWidget(self.capture_btn)
        root.addLayout(buttons)

    def _tab_capture(self):
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        form = self._form()
        outer.addLayout(form)

        # Nodes
        row = QtWidgets.QHBoxLayout()
        self.nodes_combo = QtWidgets.QComboBox()
        self.nodes_combo.addItems(["All Nodes", "Selected Nodes"])
        self.nodes_combo.currentIndexChanged.connect(self.inspect_dag)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.setToolTip("Re-read the nodes / current selection")
        refresh.clicked.connect(self.inspect_dag)
        row.addWidget(self.nodes_combo, 1)
        row.addWidget(refresh)
        form.addRow("Nodes to Capture", row)

        # Zoom
        self.zoom_spin = QtWidgets.QDoubleSpinBox()
        self.zoom_spin.setRange(0.05, 5.0)
        self.zoom_spin.setDecimals(2)
        self.zoom_spin.setSingleStep(0.25)
        self.zoom_spin.valueChanged.connect(self.update_all)
        form.addRow("Zoom Level", self.zoom_spin)

        # Margins
        self.margin_spin = QtWidgets.QSpinBox()
        self.margin_spin.setRange(0, 2000)
        self.margin_spin.setSingleStep(50)
        self.margin_spin.setSuffix(" px")
        self.margin_spin.valueChanged.connect(self.update_all)
        form.addRow("Margins", self.margin_spin)

        self.deselect_cb = QtWidgets.QCheckBox("Deselect nodes before capture")
        form.addRow(self.deselect_cb)

        # Advanced
        section = CollapsibleSection("Advanced")
        adv = self._form()

        self.crop_spin = QtWidgets.QSpinBox()
        self.crop_spin.setRange(0, 2000)
        self.crop_spin.setSingleStep(10)
        self.crop_spin.setSuffix(" px")
        self.crop_spin.setToolTip(
            "The right side of the DAG usually contains a mini version of itself.\n"
            "It is cropped out of every tile. If you scaled it down, reduce this to\n"
            "need fewer tiles.\n"
            "On Nuke 16+ the progress / cancel window sits inside this strip, so keep\n"
            "it at {}px or more to get it.".format(MIN_OVERLAY_STRIP)
        )
        self.crop_spin.valueChanged.connect(self.update_all)
        adv.addRow("Crop Right Side", self.crop_spin)

        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(0, 2)
        self.delay_spin.setSingleStep(0.1)
        self.delay_spin.setSuffix(" s")
        self.delay_spin.setToolTip(
            "Wait between moving the DAG and grabbing a tile.\n"
            "Increase if the capture shows half-redrawn tiles."
        )
        self.delay_spin.valueChanged.connect(self.update_all)
        adv.addRow("Delay Between Captures", self.delay_spin)

        section.set_body_layout(adv)
        section.toggle.toggled.connect(lambda _: QtCore.QTimer.singleShot(0, self.adjustSize))
        outer.addWidget(section)
        outer.addStretch(1)
        return page

    def _bar_box(self, title: str):
        box = QtWidgets.QGroupBox(title)
        box.setCheckable(True)
        box.toggled.connect(self.update_all)
        form = self._form()
        left, right = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        left.textChanged.connect(self.update_all)
        right.textChanged.connect(self.update_all)
        form.addRow("Left", left)
        form.addRow("Right", right)
        box.setLayout(form)
        return box, left, right

    def _tab_watermark(self):
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        form = self._form()
        outer.addLayout(form)

        self.project_edit = QtWidgets.QLineEdit()
        self.project_edit.textChanged.connect(self.update_all)
        form.addRow("Project Name", self.project_edit)

        row = QtWidgets.QHBoxLayout()
        self.version_edit = QtWidgets.QLineEdit()
        self.version_edit.textChanged.connect(self.update_all)
        reread = QtWidgets.QPushButton("Re-read Script")
        reread.setToolTip("Reset project name / version / output folder from the current Nuke script")
        reread.clicked.connect(self.refresh_script)
        row.addWidget(self.version_edit, 1)
        row.addWidget(reread)
        form.addRow("Version", row)

        self.header_box, self.header_left, self.header_right = self._bar_box("Header (top)")
        self.footer_box, self.footer_left, self.footer_right = self._bar_box("Footer (bottom)")
        outer.addWidget(self.header_box)
        outer.addWidget(self.footer_box)

        form2 = self._form()
        self.font_spin = QtWidgets.QSpinBox()
        self.font_spin.setRange(8, 100)
        self.font_spin.setSuffix(" px")
        self.font_spin.valueChanged.connect(self.update_all)
        form2.addRow("Font Size", self.font_spin)
        outer.addLayout(form2)

        hint = QtWidgets.QLabel(TOKEN_HELP)
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.preview = QtWidgets.QLabel()
        self.preview.setFrameStyle(QtWidgets.QFrame.StyledPanel)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        outer.addWidget(self.preview)
        outer.addStretch(1)
        return page

    def _tab_output(self):
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        form = self._form()
        outer.addLayout(form)

        # Folder
        row = QtWidgets.QHBoxLayout()
        self.folder_edit = QtWidgets.QLineEdit()
        self.folder_edit.setClearButtonEnabled(True)
        self.folder_edit.setToolTip("Empty = automatic: <script folder>/screenshot")
        self.folder_edit.textChanged.connect(self.update_all)
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self.browse_folder)
        open_btn = QtWidgets.QPushButton("Open")
        open_btn.clicked.connect(self.open_folder)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        row.addWidget(open_btn)
        form.addRow("Folder", row)

        # File name + format
        row = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setPlaceholderText("{script}_dag_YYYYMMDD_HHMMSS")
        self.name_edit.setToolTip("Empty = automatic name with timestamp")
        self.name_edit.textChanged.connect(self.update_all)
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(list(FORMATS))
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.format_combo)
        form.addRow("File Name", row)

        self.quality_spin = QtWidgets.QSpinBox()
        self.quality_spin.setRange(1, 100)
        form.addRow("JPG Quality", self.quality_spin)

        self.overwrite_cb = QtWidgets.QCheckBox("Overwrite if the file exists (otherwise _001, _002 ...)")
        self.overwrite_cb.toggled.connect(self.update_all)
        form.addRow(self.overwrite_cb)

        self.open_folder_cb = QtWidgets.QCheckBox("Open folder when done")
        form.addRow(self.open_folder_cb)
        self.clipboard_cb = QtWidgets.QCheckBox("Copy image to clipboard")
        form.addRow(self.clipboard_cb)

        outer.addStretch(1)
        return page

    # ---------------------------------------------------------------- settings
    def _read_config(self) -> dict:
        cfg = dict(DEFAULTS)
        try:
            saved = json.loads(self.settings.value("config", "{}"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except (TypeError, ValueError):
            pass
        return cfg

    def _apply_config(self, c: dict) -> None:
        self.folder_edit.setText(str(c["folder"]))
        self.zoom_spin.setValue(float(c["zoom"]))
        self.margin_spin.setValue(int(c["margin"]))
        self.crop_spin.setValue(int(c["crop_right"]))
        self.delay_spin.setValue(float(c["delay"]))
        self.deselect_cb.setChecked(bool(c["deselect"]))
        index = self.format_combo.findText(str(c["format"]))
        self.format_combo.setCurrentIndex(max(index, 0))
        self.quality_spin.setValue(int(c["quality"]))
        self.overwrite_cb.setChecked(bool(c["overwrite"]))
        self.open_folder_cb.setChecked(bool(c["open_folder"]))
        self.clipboard_cb.setChecked(bool(c["to_clipboard"]))
        self.header_box.setChecked(bool(c["header_on"]))
        self.header_left.setText(str(c["header_left"]))
        self.header_right.setText(str(c["header_right"]))
        self.footer_box.setChecked(bool(c["footer_on"]))
        self.footer_left.setText(str(c["footer_left"]))
        self.footer_right.setText(str(c["footer_right"]))
        self.font_spin.setValue(int(c["font_px"]))
        self._on_format_changed()

    def _collect_config(self) -> dict:
        return {
            "folder": self.folder_edit.text().strip(),
            "zoom": self.zoom_spin.value(),
            "margin": self.margin_spin.value(),
            "crop_right": self.crop_spin.value(),
            "delay": self.delay_spin.value(),
            "deselect": self.deselect_cb.isChecked(),
            "format": self.format_combo.currentText(),
            "quality": self.quality_spin.value(),
            "overwrite": self.overwrite_cb.isChecked(),
            "open_folder": self.open_folder_cb.isChecked(),
            "to_clipboard": self.clipboard_cb.isChecked(),
            "header_on": self.header_box.isChecked(),
            "header_left": self.header_left.text(),
            "header_right": self.header_right.text(),
            "footer_on": self.footer_box.isChecked(),
            "footer_left": self.footer_left.text(),
            "footer_right": self.footer_right.text(),
            "font_px": self.font_spin.value(),
        }

    def save_settings(self) -> None:
        self.settings.setValue("config", json.dumps(self._collect_config()))

    def done(self, result) -> None:
        self.save_settings()
        super(DagCapturePanel, self).done(result)

    # ---------------------------------------------------------------- paths / tokens
    def auto_dir(self) -> str:
        base = self.script["dir"] or os.path.expanduser("~")
        return os.path.join(base, "screenshot")

    def output_dir(self) -> str:
        custom = self.folder_edit.text().strip()
        return os.path.normpath(os.path.expanduser(custom)) if custom else self.auto_dir()

    def output_path(self) -> str:
        stem = self.name_edit.text().strip()
        if not stem:
            stem = "{}_dag_{}".format(self.script["stem"], datetime.now().strftime("%Y%m%d_%H%M%S"))
        base, ext = os.path.splitext(stem)
        if ext.lower() in (".png", ".jpg", ".jpeg"):
            stem = base
        path = os.path.join(self.output_dir(), stem + FORMATS[self.format_combo.currentText()])
        return path if self.overwrite_cb.isChecked() else unique_path(path)

    def tokens(self) -> dict:
        now = datetime.now()
        try:
            user = getpass.getuser()
        except Exception:  # noqa
            user = ""
        return {
            "project": self.project_edit.text(),
            "version": self.version_edit.text(),
            "script": self.script["name"],
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "user": user,
            "nodes": self.node_count,
            "zoom": "{}%".format(int(round(self.zoom_spin.value() * 100))),
        }

    def watermark_spec(self):
        """((left, right) | None for header, same for footer) with tokens resolved"""
        tokens = self.tokens()

        def bar(box, left, right):
            if not box.isChecked():
                return None
            return format_tokens(left.text(), tokens), format_tokens(right.text(), tokens)

        return (bar(self.header_box, self.header_left, self.header_right),
                bar(self.footer_box, self.footer_left, self.footer_right))

    # ---------------------------------------------------------------- slots
    def _on_format_changed(self, *_) -> None:
        self.quality_spin.setEnabled(self.format_combo.currentText() == "JPG")
        self.update_all()

    def refresh_script(self, *_) -> None:
        self.script = script_info()
        self.project_edit.setText(self.script["project"])
        self.version_edit.setText(self.script["version"])
        self.folder_edit.setPlaceholderText(self.auto_dir())
        self.update_all()

    def browse_folder(self, *_) -> None:
        start = self.output_dir()
        if not os.path.isdir(start):
            start = os.path.dirname(start) if os.path.isdir(os.path.dirname(start)) \
                else os.path.expanduser("~")
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if folder:
            self.folder_edit.setText(folder)

    def open_folder(self, *_) -> None:
        folder = self.output_dir()
        if os.path.isdir(folder):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
        else:
            self.set_status("Folder doesn't exist yet, it is created on the first capture.")

    def inspect_dag(self, *_) -> None:
        """Calculate the bounding box for the DAG"""
        self.bbox, self.node_count = nodes_bbox(self.nodes_combo.currentIndex() == 1)
        self.update_all()

    def current_plan(self):
        return compute_layout(self.bbox, self.zoom_spin.value(), self.margin_spin.value(),
                              self.dag.width(), self.dag.height(), self.crop_spin.value())

    def update_all(self, *_) -> None:
        if self._loading:
            return
        self.update_info()
        self.update_preview()

    def update_info(self) -> None:
        plan = self.current_plan()
        ok = False

        if self.bbox is None:
            text = "<span style='color:{}'><b>No nodes to capture.</b> Select some nodes " \
                   "or switch to All Nodes.</span>".format(COLOR_ERROR)
        elif plan is None:
            text = "<span style='color:{}'><b>Crop is larger than the DAG widget.</b> " \
                   "Enlarge the DAG panel or reduce Crop Right Side.</span>".format(COLOR_ERROR)
        else:
            font_px = self.font_spin.value()
            bars = int(self.header_box.isChecked()) + int(self.footer_box.isChecked())
            final_w = plan.width
            final_h = plan.height + int(font_px * 2.2) * bars
            megapixels = final_w * final_h / 1.0e6
            tiles = plan.tiles_x * plan.tiles_y
            seconds = tiles * (self.delay_spin.value() + 0.15)

            if max(final_w, final_h) > MAX_SIDE_PX:
                text = "<span style='color:{}'><b>Image too large ({} x {} px).</b> " \
                       "Lower the zoom or capture selected nodes.</span>".format(
                           COLOR_ERROR, final_w, final_h)
            else:
                ok = True
                size_color = COLOR_WARN if megapixels > WARN_MEGAPIXELS else "inherit"
                text = (
                    "<b>Image size:</b> <span style='color:{c}'>{w} x {h} px ({mp:.1f} MP)</span><br>"
                    "<b>Nodes:</b> {n} &nbsp; <b>Tiles:</b> {t} ({tx} x {ty}) &nbsp; "
                    "<b>Est. time:</b> ~{s:.1f}s<br>"
                    "<b>Save to:</b> {p}"
                ).format(c=size_color, w=final_w, h=final_h, mp=megapixels, n=self.node_count,
                         t=tiles, tx=plan.tiles_x, ty=plan.tiles_y, s=seconds,
                         p=html.escape(self.output_path()))
                if tiles > 1:
                    text += "<br><i>Enlarge the DAG panel to reduce the number of tiles.</i>"

        self.info.setText(text)
        self.capture_btn.setEnabled(ok)

    def update_preview(self) -> None:
        header, footer = self.watermark_spec()
        if not header and not footer:
            self.preview.setText("Watermark off")
            return
        base = QtGui.QImage(520, 48, QtGui.QImage.Format_RGB32)
        base.fill(QtGui.QColor(CAPTURE_BG))
        self.preview.setPixmap(QtGui.QPixmap.fromImage(
            add_watermark(base, header, footer, self.font_spin.value())))

    def set_status(self, text: str, error: bool = False) -> None:
        if error:
            text = "<span style='color:{}'>{}</span>".format(COLOR_ERROR, text)
        self.status.setText(text)

    # ---------------------------------------------------------------- capture
    def do_capture(self, *_) -> None:
        """Start the capture thread"""
        self.inspect_dag()  # bbox / selection might have changed since the panel opened
        plan = self.current_plan()
        if plan is None:
            return

        path = self.output_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as exc:
            self.set_status("Couldn't create folder: {}".format(html.escape(str(exc))), error=True)
            return

        self.save_settings()
        header, footer = self.watermark_spec()
        fmt = self.format_combo.currentText()
        self.pending = {
            "path": path,
            "format": fmt,
            "quality": self.quality_spin.value() if fmt == "JPG" else -1,
            "watermark": (header, footer),
            "font_px": self.font_spin.value(),
            "clipboard": self.clipboard_cb.isChecked(),
            "open_folder": self.open_folder_cb.isChecked(),
        }

        # Deselect nodes if required
        self.selection = []
        if self.deselect_cb.isChecked():
            self.selection = list(nuke.selectedNodes())
            for node in self.selection:
                node.setSelected(False)

        thread = self.capture_thread
        thread.plan = plan
        thread.zoom = self.zoom_spin.value()
        thread.delay = self.delay_spin.value()
        thread.restore = (nuke.zoom(), nuke.center())

        self.set_status("")
        self.hide()
        self.show_overlay()
        thread.start()

    def show_overlay(self) -> None:
        strip = self.crop_spin.value()
        in_strip = strip >= MIN_OVERLAY_STRIP
        if not in_strip and nuke.NUKE_VERSION_MAJOR >= 16:
            return  # would end up in the screen grab, so no overlay

        x = self.dag.width() - strip + (strip - OVERLAY_WIDTH) // 2 if in_strip \
            else (self.dag.width() - OVERLAY_WIDTH) // 2
        self.overlay = ProgressOverlay()
        self.overlay.cancel_requested.connect(self.capture_thread.cancel)
        self.overlay.adjustSize()
        self.overlay.move(self.dag.mapToGlobal(QtCore.QPoint(x, 12)))
        self.overlay.show()
        QtWidgets.QApplication.processEvents()

    def close_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None

    def on_progress(self, done: int, total: int) -> None:
        if self.overlay is not None:
            self.overlay.set_progress(done, total)

    def on_thread_finished(self) -> None:
        """Restore selection, add the watermark, save, report"""
        self.close_overlay()
        for node in self.selection:
            node.setSelected(True)
        self.selection = []

        thread = self.capture_thread
        image, thread.image = thread.image, None

        self.show()
        self.raise_()
        self.activateWindow()

        if thread.error:
            self.set_status("Capture failed: {} (see Script Editor)".format(
                html.escape(thread.error)), error=True)
            return
        if image is None:
            self.set_status("Capture cancelled.")
            return

        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
        try:
            header, footer = self.pending["watermark"]
            image = add_watermark(image, header, footer, self.pending["font_px"])
            self.save_image(image)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def save_image(self, image) -> None:
        path = self.pending["path"]
        if not image.save(path, self.pending["format"], self.pending["quality"]):
            self.set_status("Couldn't write {}".format(html.escape(path)), error=True)
            return

        if self.pending["clipboard"]:
            QtWidgets.QApplication.clipboard().setImage(image)

        size_mb = os.path.getsize(path) / 1048576.0
        link = QtCore.QUrl.fromLocalFile(path).toString()
        self.set_status("Saved <a href=\"{}\">{}</a> - {} x {} px, {:.1f} MB".format(
            link, html.escape(os.path.basename(path)), image.width(), image.height(), size_mb))
        nuke.tprint("DAG capture saved: {}".format(path))

        if self.pending["open_folder"]:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(path)))
        self.update_all()  # refresh the "Save to" path (next free name)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------
PANEL_NAME = "ccDagCapturePanel"

# Optional, read by CC autoMenu for the menu shortcut, e.g. "ctrl+alt+shift+c"
keyShortCut = None


def open_dag_capture() -> None:
    """Opens the DAG capture panel (one at a time).

    autoMenu re-executes this file on every click, so the existing panel is looked up
    through Qt instead of a module-level variable.
    """
    logging.info("Opening dag capture window")
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == PANEL_NAME:
            if widget.capture_thread.isRunning():
                return
            widget.close()
            widget.deleteLater()

    panel = DagCapturePanel()
    panel.show()


def run() -> None:
    """Entry point used by CC autoMenu"""
    open_dag_capture()


if __name__ == '__main__':
    open_dag_capture()