from __future__ import annotations

import weakref
from typing import Literal

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget

from shared.ui_tokens import DesignTokens, css_color_to_qcolor, tokens_for_mode

ThemePreference = Literal["auto", "light", "dark"]
StatusRole = Literal["waiting", "success", "error", "offline"]


class ThemeManager:
    """Central theme source-of-truth.

    Synchronizes the custom DesignToken system with QFluentWidgets
    and regenerates QSS on every theme change.
    """

    def __init__(self) -> None:
        self._app: QApplication | None = None
        self._preference: ThemePreference = "auto"
        self._widgets: weakref.WeakSet[QWidget] = weakref.WeakSet()

    def initialize(
        self,
        app: QApplication,
        preference: ThemePreference = "auto",
    ) -> None:
        self._app = app
        self.set_preference(preference)

    def register(self, widget: QWidget) -> None:
        self._widgets.add(widget)
        self.apply_widget_theme(widget)

    def set_preference(self, preference: ThemePreference) -> None:
        self._preference = preference
        self._apply_qfluent_theme()
        self.apply()

    @property
    def preference(self) -> ThemePreference:
        return self._preference

    def tokens(self) -> DesignTokens:
        return tokens_for_mode("dark" if self.is_dark() else "light")

    def is_dark(self) -> bool:
        if self._preference == "dark":
            return True
        if self._preference == "light":
            return False

        try:
            from qfluentwidgets import isDarkTheme

            return bool(isDarkTheme())
        except Exception:
            app = self._app or QApplication.instance()
            if not app:
                return False
            color = app.palette().color(QPalette.ColorRole.Window)
            return color.lightness() < 128

    # ── stylesheets ──────────────────────────────────────────────

    def status_badge_stylesheet(self, role: StatusRole) -> str:
        token = {
            "waiting": self.tokens().badge_waiting,
            "success": self.tokens().badge_success,
            "error": self.tokens().badge_error,
            "offline": self.tokens().badge_offline,
        }[role]
        t = self.tokens()
        return f"""
            QLabel {{
                padding: 5px 12px;
                border-radius: {t.radius_sm}px;
                background: {token.background};
                color: {token.foreground};
                font-weight: 600;
            }}
        """

    def panel_stylesheet(self) -> str:
        tokens = self.tokens()
        return f"""
            QFrame {{
                border: 1px solid {tokens.card_border};
                border-radius: {tokens.radius_lg}px;
                background: {tokens.card_surface};
            }}
        """

    def preview_stylesheet(self) -> str:
        tokens = self.tokens()
        return f"""
            QLabel {{
                border: 1px solid {tokens.panel_border};
                border-radius: {tokens.radius_lg}px;
                background: {tokens.preview_background};
                color: {tokens.preview_text};
                font-size: 24px;
                font-weight: 700;
            }}
        """

    def scroll_area_stylesheet(self) -> str:
        tokens = self.tokens()
        return f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                width: 10px;
                margin: 6px 2px 6px 2px;
                border: none;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                min-height: 36px;
                border-radius: 4px;
                background: {tokens.scrollbar};
            }}
            QScrollBar::handle:vertical:hover {{
                background: {tokens.scrollbar_hover};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                height: 0;
                border: none;
                background: transparent;
            }}
            QScrollBar:horizontal {{
                height: 10px;
                margin: 2px 6px 2px 6px;
                border: none;
                background: transparent;
            }}
            QScrollBar::handle:horizontal {{
                min-width: 36px;
                border-radius: 4px;
                background: {tokens.scrollbar};
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {tokens.scrollbar_hover};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal,
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                width: 0;
                border: none;
                background: transparent;
            }}
        """

    # ── apply cycle ──────────────────────────────────────────────

    def apply(self) -> None:
        app = self._app or QApplication.instance()
        if app:
            self._apply_palette(app, self.tokens())
            app.setStyleSheet(self._app_stylesheet())

        for widget in list(self._widgets):
            self.apply_widget_theme(widget)

    def apply_widget_theme(self, widget: QWidget) -> None:
        tokens = self.tokens()
        self._apply_qfluent_widget_overrides(widget, tokens)
        apply_theme = getattr(widget, "apply_theme", None)
        if callable(apply_theme):
            apply_theme(tokens)
        widget.update()

    def _apply_qfluent_theme(self) -> None:
        try:
            from qfluentwidgets import Theme, setTheme, setThemeColor

            theme = {
                "auto": Theme.AUTO,
                "light": Theme.LIGHT,
                "dark": Theme.DARK,
            }[self._preference]
            setTheme(theme)
            setThemeColor(self.tokens().primary)
        except Exception:
            return

    def _app_stylesheet(self) -> str:
        tokens = self.tokens()
        primary_button_text = tokens.background if tokens.mode == "dark" else "white"
        ss = f"""
            QWidget {{
                color: {tokens.text_primary};
            }}
            FluentWindow,
            TitleBar,
            FluentTitleBar,
            FluentWidgetTitleBar,
            StackedWidget,
            PopUpAniStackedWidget,
            NavigationInterface,
            NavigationPanel,
            SmoothScrollArea,
            ScrollArea,
            QWidget#qt_scrollarea_viewport {{
                background: {tokens.background};
            }}
            QWidget#operatorWindow,
            QWidget#streamerWindow {{
                background: {tokens.background};
            }}
            QWidget#dashboardView,
            QWidget#previewView,
            QWidget#logsView,
            QWidget#settingsView,
            QWidget#statusView {{
                background: {tokens.background};
            }}
            QWidget#dashboardContent,
            QWidget#previewContent,
            QWidget#logsContent,
            QWidget#settingsView,
            QWidget#statusContent {{
                background: {tokens.background};
            }}
            BodyLabel {{
                color: {tokens.text_primary};
            }}
            QPlainTextEdit {{
                border: 1px solid {tokens.card_border};
                border-radius: {tokens.radius_md}px;
                background: {tokens.card_surface};
                color: {tokens.text_primary};
                selection-background-color: {tokens.primary};
                padding: 10px;
            }}
            LineEdit, PasswordLineEdit, ComboBox, SpinBox, DoubleSpinBox {{
                color: {tokens.text_primary};
            }}
            PushButton, PrimaryPushButton {{
                border-radius: {tokens.radius_sm}px;
                padding: 7px 14px;
                font-weight: 600;
            }}
            PushButton {{
                border: 1px solid {tokens.card_border};
                background: {tokens.card_surface};
                color: {tokens.text_primary};
            }}
            PushButton:hover {{
                background-color: {tokens.hover_background};
                border: 1px solid {tokens.hover_border};
            }}
            PrimaryPushButton {{
                border: 1px solid {tokens.primary};
                background: {tokens.primary};
                color: {primary_button_text};
            }}
            PrimaryPushButton:hover {{
                border: 1px solid {tokens.hover_border};
                background: {tokens.primary_hover};
            }}
        """

        # Dark-mode-specific polish
        if tokens.mode == "dark":
            ss += f"""
            QPlainTextEdit {{
                background: #0B1220;
            }}
            PushButton:hover {{
                background-color: {tokens.hover_background};
                border: 1px solid {tokens.hover_border};
            }}
            PrimaryPushButton:hover {{
                border: 1px solid {tokens.hover_border};
                background: {tokens.primary_hover};
            }}
            LineEdit, PasswordLineEdit, ComboBox, SpinBox, DoubleSpinBox {{
                background: #0B1220;
                border: 1px solid {tokens.card_border};
                border-radius: {tokens.radius_sm}px;
                padding: 6px 10px;
            }}
            LineEdit:hover,
            PasswordLineEdit:hover,
            ComboBox:hover,
            SpinBox:hover,
            DoubleSpinBox:hover {{
                background-color: {tokens.hover_background};
                border: 1px solid {tokens.hover_border};
            }}
            LineEdit:focus,
            PasswordLineEdit:focus,
            ComboBox:focus,
            SpinBox:focus,
            DoubleSpinBox:focus {{
                border-color: {tokens.primary};
            }}
        """

        return ss

    @staticmethod
    def _apply_palette(app: QApplication, tokens: DesignTokens) -> None:
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Window, css_color_to_qcolor(tokens.background))
        palette.setColor(QPalette.ColorRole.Base, css_color_to_qcolor(tokens.background))
        palette.setColor(QPalette.ColorRole.AlternateBase, css_color_to_qcolor(tokens.card_surface))
        palette.setColor(QPalette.ColorRole.Button, css_color_to_qcolor(tokens.card_surface))
        palette.setColor(QPalette.ColorRole.WindowText, css_color_to_qcolor(tokens.text_primary))
        palette.setColor(QPalette.ColorRole.Text, css_color_to_qcolor(tokens.text_primary))
        palette.setColor(QPalette.ColorRole.ButtonText, css_color_to_qcolor(tokens.text_primary))
        palette.setColor(QPalette.ColorRole.ToolTipBase, css_color_to_qcolor(tokens.card_surface))
        palette.setColor(QPalette.ColorRole.ToolTipText, css_color_to_qcolor(tokens.text_primary))
        palette.setColor(QPalette.ColorRole.Highlight, css_color_to_qcolor(tokens.primary))
        palette.setColor(QPalette.ColorRole.HighlightedText, css_color_to_qcolor(tokens.background))
        app.setPalette(palette)

    @classmethod
    def _apply_qfluent_widget_overrides(
        cls,
        widget: QWidget,
        tokens: DesignTokens,
    ) -> None:
        background = css_color_to_qcolor(tokens.background)

        set_mica = getattr(widget, "setMicaEffectEnabled", None)
        if callable(set_mica):
            set_mica(False)

        set_custom_background = getattr(widget, "setCustomBackgroundColor", None)
        if callable(set_custom_background):
            set_custom_background(background, background)

        set_background = getattr(widget, "setBackgroundColor", None)
        if callable(set_background):
            set_background(background)

        navigation = getattr(widget, "navigationInterface", None)
        panel = getattr(navigation, "panel", None)
        if panel is None:
            return

        nav_override = f"""
            NavigationPanel {{
                background-color: {tokens.background};
                border: none;
            }}
            NavigationPanel[menu="true"] {{
                background-color: {tokens.card_surface};
                border: 1px solid {tokens.card_border};
            }}
            ScrollArea,
            QWidget#scrollWidget {{
                background-color: {tokens.background};
                border: none;
            }}
        """
        cls._set_style_override(panel, "_skyguard_base_nav_style", nav_override)

        scroll_widget = getattr(panel, "scrollWidget", None)
        if scroll_widget is not None:
            cls._set_style_override(
                scroll_widget,
                "_skyguard_base_scroll_widget_style",
                f"QWidget#scrollWidget {{ background-color: {tokens.background}; }}",
            )

    @staticmethod
    def _set_style_override(widget: QWidget, base_property: str, override: str) -> None:
        base_style = widget.property(base_property)
        if base_style is None:
            base_style = widget.styleSheet()
            widget.setProperty(base_property, base_style)
        widget.setStyleSheet(f"{base_style}\n{override}")


_THEME_MANAGER = ThemeManager()


def theme_manager() -> ThemeManager:
    return _THEME_MANAGER
