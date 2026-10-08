from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from shared.ui_theme import StatusRole, ThemePreference, theme_manager
from shared.ui_tokens import DesignTokens, css_color_to_qcolor


class ThemedStatusBadge(QLabel):
    """Semantic badge that updates its look via the ThemeManager."""

    def __init__(self, text: str, role: StatusRole = "offline") -> None:
        super().__init__(text)
        self._role = role
        self.setMinimumHeight(28)
        theme_manager().register(self)

    def set_state(self, text: str, role: StatusRole) -> None:
        if text == self.text() and role == self._role:
            return
        self._role = role
        self.setText(text)
        self.apply_theme(theme_manager().tokens())

    def apply_theme(self, _tokens: DesignTokens) -> None:
        self.setStyleSheet(theme_manager().status_badge_stylesheet(self._role))


class ThemedPage(QWidget):
    """Page-level widget that repaints on theme change."""

    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setAutoFillBackground(True)
        theme_manager().register(self)

    def apply_theme(self, _tokens: DesignTokens) -> None:
        self.update()


class AcrylicGlowFrame(QFrame):
    """Styled card with a stable surface, subtle border, and restrained hover.

    All cards share the same premium visual style.
    The ``variant`` parameter is accepted for backward compatibility
    but no longer changes the appearance.
    """

    def __init__(self, variant: str = "standard", radius: int | None = None) -> None:
        super().__init__()
        self._radius = radius
        self._hovered = False
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        theme_manager().register(self)

    def apply_theme(self, _tokens: DesignTokens) -> None:
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        tokens = theme_manager().tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = self._radius or tokens.radius_lg
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # fill
        painter.fillPath(path, css_color_to_qcolor(tokens.card_surface))
        if self._hovered:
            painter.fillPath(path, css_color_to_qcolor(tokens.hover_background))

        # Cheap in-paint depth. QGraphicsDropShadowEffect is expensive while scrolling.
        shadow_color = css_color_to_qcolor(tokens.card_shadow)
        shadow_color.setAlpha(min(shadow_color.alpha(), 46))
        painter.setPen(QPen(shadow_color, 1))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius, radius)

        # accent border
        border_color = tokens.hover_border if self._hovered else tokens.card_border
        painter.setPen(QPen(css_color_to_qcolor(border_color), 1))
        painter.drawPath(path)

        # inner highlight border – subtle in dark, visible in light
        inner = self.rect().adjusted(4, 4, -4, -4)
        inner_path = QPainterPath()
        inner_r = max(4, radius - 4)
        inner_path.addRoundedRect(inner, inner_r, inner_r)
        highlight_alpha = 12 if tokens.mode == "dark" else 42
        painter.setPen(QPen(QColor(255, 255, 255, highlight_alpha), 1))
        painter.drawPath(inner_path)


class CustomizeCard(AcrylicGlowFrame):
    """Card with theme switching controls."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("customizeCard")
        self._build_controls()

    def _build_controls(self) -> None:
        from qfluentwidgets import BodyLabel, ComboBox

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = BodyLabel("Customize")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(BodyLabel("Theme"))
        self._theme_combo = ComboBox()
        self._theme_combo.addItems(["Auto", "Light", "Dark"])
        self._theme_combo.setCurrentText(theme_manager().preference.capitalize())
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        row.addWidget(self._theme_combo, 1)
        layout.addLayout(row)

    @staticmethod
    def _on_theme_changed(text: str) -> None:
        pref: ThemePreference = text.lower()  # type: ignore[assignment]
        theme_manager().set_preference(pref)
