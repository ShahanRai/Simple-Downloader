"""
Executive Modern UI Design System for Internet Downloader.
Implements dark obsidian surfaces, electric blue gradients, glowing status accents,
smooth progress indicators, dynamic segment bars, and executive desktop aesthetics.
"""

from PyQt6.QtWidgets import (
    QWidget, QFrame, QPushButton, QLineEdit, QProgressBar, QLabel,
    QGraphicsDropShadowEffect
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient, QRadialGradient,
    QFont, QPainterPath, QCursor
)
from PyQt6.QtCore import Qt, QRectF, QSize, pyqtSignal


class NeumorphicTheme:
    DARK = {
        "name": "dark",
        "bg": "#0b0f19",
        "card": "#111827",
        "card_hover": "#1e293b",
        "card_sunken": "#080c14",
        "shadow_light": "#1e293b",
        "shadow_dark": "#05070d",
        "border": "#1f293d",
        "border_light": "#2d3a52",
        "text_primary": "#f8fafc",
        "text_secondary": "#94a3b8",
        "text_muted": "#64748b",
        "accent": "#3b82f6",
        "accent_hover": "#60a5fa",
        "accent_gradient_start": "#3b82f6",
        "accent_gradient_end": "#1d4ed8",
        "accent_text": "#ffffff",
        "accent_glow": "rgba(59, 130, 246, 0.35)",
        "green": "#10b981",
        "green_glow": "rgba(16, 185, 129, 0.25)",
        "red": "#f43f5e",
        "amber": "#f59e0b",
        "cyan": "#06b6d4",
        "purple": "#8b5cf6",
    }

    LIGHT = {
        "name": "light",
        "bg": "#f1f5f9",
        "card": "#ffffff",
        "card_hover": "#f8fafc",
        "card_sunken": "#e2e8f0",
        "shadow_light": "#ffffff",
        "shadow_dark": "#cbd5e1",
        "border": "#e2e8f0",
        "border_light": "#cbd5e1",
        "text_primary": "#0f172a",
        "text_secondary": "#475569",
        "text_muted": "#94a3b8",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "accent_gradient_start": "#2563eb",
        "accent_gradient_end": "#1e40af",
        "accent_text": "#ffffff",
        "accent_glow": "rgba(37, 99, 235, 0.25)",
        "green": "#059669",
        "green_glow": "rgba(5, 150, 105, 0.2)",
        "red": "#dc2626",
        "amber": "#d97706",
        "cyan": "#0891b2",
        "purple": "#7c3aed",
    }

    current = DARK

    @classmethod
    def set_theme(cls, name: str):
        if name.lower() == "light":
            cls.current = cls.LIGHT
        else:
            cls.current = cls.DARK


class NeumorphicCard(QFrame):
    """
    A sleek modern card container with subtle borders and soft depth.
    """
    def __init__(self, parent=None, is_raised: bool = True, radius: float = 12.0):
        super().__init__(parent)
        self.is_raised = is_raised
        self.radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event):
        t = NeumorphicTheme.current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        r = self.radius

        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        if self.is_raised:
            # Card surface
            painter.setPen(QPen(QColor(t["border"]), 1))
            painter.setBrush(QBrush(QColor(t["card"])))
            painter.drawPath(path)

            # Subtle top highlight rim
            painter.setPen(QPen(QColor(t["border_light"]), 1))
            painter.drawLine(int(rect.left() + r), int(rect.top()), int(rect.right() - r), int(rect.top()))
        else:
            # Recessed / Sunken container
            painter.setPen(QPen(QColor(t["border"]), 1))
            painter.setBrush(QBrush(QColor(t["card_sunken"])))
            painter.drawPath(path)


class NeumorphicButton(QPushButton):
    """
    Tactile executive button with smooth hover glow and gradient accents.
    """
    def __init__(self, text: str = "", parent=None, variant: str = "default", radius: float = 10.0):
        super().__init__(text, parent)
        self.variant = variant  # 'default', 'primary', 'success', 'danger', 'ghost'
        self.radius = radius
        self.is_hovered = False
        self.is_pressed = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.setMinimumHeight(38)

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        t = NeumorphicTheme.current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        r = self.radius

        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        if self.variant == "primary":
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            if self.is_hovered:
                grad.setColorAt(0.0, QColor(t["accent_hover"]))
                grad.setColorAt(1.0, QColor(t["accent"]))
            else:
                grad.setColorAt(0.0, QColor(t["accent_gradient_start"]))
                grad.setColorAt(1.0, QColor(t["accent_gradient_end"]))

            painter.setPen(QPen(QColor(t["accent_hover"]), 1))
            painter.setBrush(QBrush(grad))
            painter.drawPath(path)
            text_color = QColor(t["accent_text"])

        elif self.variant == "success":
            base_color = QColor(t["green"]).lighter(110) if self.is_hovered else QColor(t["green"])
            painter.setPen(QPen(base_color.lighter(120), 1))
            painter.setBrush(QBrush(base_color))
            painter.drawPath(path)
            text_color = QColor("#ffffff")

        elif self.variant == "danger":
            base_color = QColor(t["red"]).lighter(110) if self.is_hovered else QColor(t["red"])
            painter.setPen(QPen(base_color.lighter(120), 1))
            painter.setBrush(QBrush(base_color))
            painter.drawPath(path)
            text_color = QColor("#ffffff")

        elif self.variant == "ghost":
            if self.is_hovered:
                painter.setPen(QPen(QColor(t["border_light"]), 1))
                painter.setBrush(QBrush(QColor(t["card_hover"])))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            text_color = QColor(t["text_primary"])

        else:  # default
            bg = QColor(t["card_hover"]) if self.is_hovered else QColor(t["card"])
            border_c = QColor(t["accent"]) if self.is_hovered else QColor(t["border"])
            painter.setPen(QPen(border_c, 1))
            painter.setBrush(QBrush(bg))
            painter.drawPath(path)
            text_color = QColor(t["text_primary"])

        # Offset text slightly when clicked for tactile feedback
        offset = 1 if self.is_pressed else 0
        text_rect = rect.adjusted(offset + 8, offset, offset - 8, offset)
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())


class NeumorphicLineEdit(QLineEdit):
    """
    Sleek inset text field with high-contrast text and glowing focus border.
    """
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFont(QFont("Segoe UI", 9))
        self.setMinimumHeight(40)
        self._apply_style()

    def _apply_style(self):
        t = NeumorphicTheme.current
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['card_sunken']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 10px;
                padding: 6px 14px;
                selection-background-color: {t['accent']};
            }}
            QLineEdit:focus {{
                border: 1.5px solid {t['accent']};
                background-color: {t['card_sunken']};
            }}
        """)


class NeumorphicProgressBar(QWidget):
    """
    Modern pill progress bar with smooth dual-tone gradient fill.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self.setMinimumHeight(24)

    def setValue(self, val: float):
        self._value = max(0.0, min(100.0, float(val)))
        self.update()

    def value(self) -> float:
        return self._value

    def paintEvent(self, event):
        t = NeumorphicTheme.current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        r = rect.height() / 2.0

        # Recessed background track
        track_path = QPainterPath()
        track_path.addRoundedRect(rect, r, r)
        painter.setPen(QPen(QColor(t["border"]), 1))
        painter.setBrush(QBrush(QColor(t["card_sunken"])))
        painter.drawPath(track_path)

        # Progress fill
        if self._value > 0.0:
            fill_width = max(r * 2, rect.width() * (self._value / 100.0))
            fill_rect = QRectF(rect.x(), rect.y(), fill_width, rect.height())

            grad = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
            if self._value >= 99.9:
                grad.setColorAt(0.0, QColor(t["green"]))
                grad.setColorAt(1.0, QColor(t["cyan"]))
            else:
                grad.setColorAt(0.0, QColor(t["accent"]))
                grad.setColorAt(1.0, QColor(t["cyan"]))

            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, r, r)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(fill_path)

        # Value text overlay
        painter.setPen(QColor(t["text_primary"]))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        text = f"{self._value:.1f}%"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class NeumorphicSegmentBar(QWidget):
    """
    Real-Time Dynamic Segment Visualizer (matching IDM's CFragmentsList bar).
    Draws dynamic file ranges and active connection threads in real-time!
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.file_size = 0
        self.setMinimumHeight(28)
        self.setToolTip("Dynamic Multi-Connection Segment Allocation (IDM Engine)")

    def update_segments(self, segments: list, file_size: int):
        self.segments = segments
        self.file_size = file_size
        self.update()

    def paintEvent(self, event):
        t = NeumorphicTheme.current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        r = 8.0

        # Recessed background track
        track_path = QPainterPath()
        track_path.addRoundedRect(rect, r, r)
        painter.setPen(QPen(QColor(t["border"]), 1))
        painter.setBrush(QBrush(QColor(t["card_sunken"])))
        painter.drawPath(track_path)

        if not self.segments or self.file_size <= 0:
            painter.setPen(QColor(t["text_muted"]))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "⚡ Multi-Stream Dynamic Segmentation Engine: Ready")
            return

        colors = [
            QColor("#3b82f6"),  # Blue
            QColor("#10b981"),  # Emerald
            QColor("#06b6d4"),  # Cyan
            QColor("#8b5cf6"),  # Purple
            QColor("#f59e0b"),  # Amber
            QColor("#38bdf8"),  # Sky
            QColor("#ec4899"),  # Pink
            QColor("#14b8a6"),  # Teal
            QColor("#6366f1"),  # Indigo
            QColor("#84cc16"),  # Lime
            QColor("#a855f7"),  # Violet
            QColor("#0284c7"),  # Light Blue
            QColor("#059669"),  # Dark Emerald
            QColor("#e11d48"),  # Rose
            QColor("#d97706"),  # Dark Amber
            QColor("#2563eb"),  # Royal Blue
        ]

        w = rect.width()
        total = float(self.file_size)

        for s in self.segments:
            seg_start = s.start_byte / total
            seg_end = s.end_byte / total
            seg_curr = s.current_byte / total

            x_start = rect.x() + (seg_start * w)
            x_end = rect.x() + (seg_end * w)
            x_curr = rect.x() + (seg_curr * w)

            seg_w = max(1.0, x_end - x_start)
            done_w = max(0.0, min(seg_w, x_curr - x_start))

            color = colors[s.id % len(colors)]

            # Draw downloaded portion
            if done_w > 0:
                seg_rect = QRectF(x_start, rect.y() + 2, done_w, rect.height() - 4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(seg_rect, 4, 4)

            # Draw split delimiter
            painter.setPen(QPen(QColor("#ffffff"), 1.0, Qt.PenStyle.DotLine))
            painter.drawLine(int(x_end), int(rect.y() + 2), int(x_end), int(rect.bottom() - 2))


def get_global_stylesheet() -> str:
    """Generates cohesive executive styling for tables, menus, scrollbars, headers."""
    t = NeumorphicTheme.current
    return f"""
        QWidget {{
            background-color: {t['bg']};
            color: {t['text_primary']};
            font-family: 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif;
        }}
        QMenu {{
            background-color: {t['card']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
            border-radius: 10px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 8px 24px;
            border-radius: 6px;
            font-size: 9pt;
        }}
        QMenu::item:selected {{
            background-color: {t['accent']};
            color: #ffffff;
        }}
        QScrollBar:vertical {{
            background: {t['card_sunken']};
            width: 8px;
            border-radius: 4px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {t['border_light']};
            min-height: 24px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {t['accent']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QHeaderView::section {{
            background-color: {t['card']};
            color: {t['text_secondary']};
            padding: 10px 12px;
            border: none;
            border-bottom: 2px solid {t['border']};
            font-weight: 700;
            font-size: 8.5pt;
            letter-spacing: 0.5px;
        }}
        QTableWidget {{
            background-color: {t['card_sunken']};
            border: 1px solid {t['border']};
            border-radius: 12px;
            gridline-color: transparent;
            selection-background-color: {t['card_hover']};
        }}
        QTableWidget::item {{
            padding: 10px 12px;
            border-bottom: 1px solid {t['border']};
            font-size: 9pt;
        }}
        QTableWidget::item:selected {{
            background-color: {t['card_hover']};
            color: {t['text_primary']};
            border-left: 3px solid {t['accent']};
        }}
    """
