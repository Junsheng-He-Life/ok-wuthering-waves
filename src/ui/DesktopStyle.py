"""Shared visual language for the focused desktop panel."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


STYLE = '''
QMainWindow, QWidget#appRoot { background: #f4f6f9; color: #172b3a; }
QWidget { font-family: "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue"; font-size: 13px; color: #172b3a; }
QFrame#sidebar { background: #122b32; border: none; }
QFrame#sidebar QLabel { color: #a7bfc4; background: transparent; }
QFrame#sidebar QLabel#brand { color: white; font-size: 24px; font-weight: 700; }
QFrame#sidebar QPushButton { background: transparent; color: #b3c9cd; border: 0; text-align: left; padding: 13px 16px; border-radius: 9px; font-size: 14px; }
QFrame#sidebar QPushButton:checked { background: #25464d; color: white; font-weight: 600; }
QFrame#sidebar QPushButton:hover { background: #203f46; }
QLabel#title { font-size: 28px; font-weight: 700; color: #122b32; }
QLabel#subtitle { color: #6c7b87; font-size: 13px; }
QLabel#cardTitle { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #72818d; }
QLabel#eyebrow { color: #799095; font-size: 11px; font-weight: 600; }
QLabel#statusChip { background: #e3eeec; color: #28665c; border-radius: 12px; padding: 6px 12px; font-size: 12px; }
QFrame#card { background: white; border: 1px solid #e2e8ed; border-radius: 14px; }
QFrame#card QLabel { background: transparent; border: none; }
QFrame#notice { background: #fff5e2; border: 1px solid #f0dfbc; border-radius: 10px; }
QFrame#notice QLabel { color: #785c28; background: transparent; }
QPushButton { background: white; color: #294451; border: 1px solid #d7e0e5; padding: 9px 15px; border-radius: 8px; font-weight: 500; }
QPushButton:hover { background: #f0f6f5; border-color: #9cbbb5; }
QPushButton:pressed { background: #e1edeb; }
QPushButton:disabled { background: #edf1f4; color: #9aa7b0; border-color: #e4e9ed; }
QPushButton#primary { background: #147c6c; border: 1px solid #147c6c; color: white; font-size: 15px; font-weight: 600; padding: 12px 22px; }
QPushButton#primary:hover { background: #106c5e; }
QPushButton#primary:disabled { background: #c4d8d3; border-color: #c4d8d3; color: #6f8c85; }
QPushButton#quiet { border: none; background: transparent; color: #147c6c; padding: 5px 4px; }
QPushButton#danger { color: #a14840; border-color: #e7cecb; }
QPushButton#segment { background: #f1f4f6; border: 1px solid transparent; padding: 9px 12px; }
QPushButton#segment:checked { background: #e6f2ef; color: #147c6c; border-color: #b0d4ca; }
QComboBox, QSpinBox, QLineEdit { background: #fcfdfd; border: 1px solid #d9e2e7; border-radius: 7px; padding: 8px 10px; min-height: 22px; selection-background-color: #147c6c; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #147c6c; }
QComboBox:disabled, QSpinBox:disabled { color: #9ca8b0; background: #f1f4f6; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(@icons@/desktop-chevron-down.svg); width: 12px; height: 8px; }
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 22px; background: #f0f5f6; }
QSpinBox::up-arrow { image: url(@icons@/desktop-chevron-up.svg); width: 10px; height: 7px; }
QSpinBox::down-arrow { image: url(@icons@/desktop-chevron-down.svg); width: 10px; height: 7px; }
QComboBox QAbstractItemView { background: white; color: #172b3a; selection-background-color: #e2f1ec; selection-color: #147c6c; padding: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #becdd4; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: #147c6c; border-color: #147c6c; image: url(@icons@/desktop-check.svg); }
QProgressBar { background: #e9efef; border: none; border-radius: 3px; min-height: 5px; max-height: 5px; }
QProgressBar::chunk { background: #3aa18e; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd6db; border-radius: 3px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QPlainTextEdit { background: #f7f9fb; border: 1px solid #e0e7eb; border-radius: 8px; padding: 10px; color: #445965; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: white; border: 1px solid #e2e8ed; border-radius: 10px; padding: 16px; margin-bottom: 8px; }
QListWidget::item:selected { background: #e9f4f0; border-color: #8ebeb1; color: #193c35; }
QToolTip { background: #233e46; color: white; border: none; padding: 7px; }
'''.replace('@icons@', (Path(__file__).resolve().parents[2] / 'icons').as_posix())


def label(text, kind='', wrap=False):
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.PlainText)
    return widget


def button(text, kind=''):
    widget = QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def card(title, description=None):
    frame = QFrame()
    frame.setObjectName('card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 19, 22, 20)
    layout.setSpacing(12)
    if title:
        layout.addWidget(label(title, 'cardTitle'))
    if description:
        layout.addWidget(label(description, 'muted', True))
    return frame, layout


def field(title, widget, note=None):
    layout = QVBoxLayout()
    layout.setSpacing(6)
    layout.addWidget(label(title))
    layout.addWidget(widget)
    if note:
        layout.addWidget(label(note, 'muted', True))
    return layout


def row(*widgets):
    layout = QHBoxLayout()
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    return layout
