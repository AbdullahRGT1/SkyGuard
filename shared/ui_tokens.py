from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QColor

ThemeMode = Literal["light", "dark"]


@dataclass(frozen=True, slots=True)
class BadgeToken:
    background: str
    foreground: str


@dataclass(frozen=True, slots=True)
class DesignTokens:
    mode: ThemeMode
    background: str
    card_surface: str
    card_border: str
    card_shadow: str
    hover_background: str
    hover_border: str
    primary: str
    primary_hover: str
    text_primary: str
    text_secondary: str
    panel_border: str
    preview_background: str
    preview_text: str
    scrollbar: str
    scrollbar_hover: str
    radius_sm: int
    radius_md: int
    radius_lg: int
    spacing_sm: int
    spacing_md: int
    spacing_lg: int
    badge_waiting: BadgeToken
    badge_success: BadgeToken
    badge_error: BadgeToken
    badge_offline: BadgeToken


LIGHT_TOKENS = DesignTokens(
    mode="light",
    background="#F0F8FF",
    card_surface="#F4FAFF",
    card_border="rgba(33, 150, 243, 0.34)",
    card_shadow="rgba(33, 150, 243, 0.22)",
    hover_background="rgba(33, 150, 243, 0.08)",
    hover_border="rgba(33, 150, 243, 0.30)",
    primary="#2196F3",
    primary_hover="#1976D2",
    text_primary="#202124",
    text_secondary="#757575",
    panel_border="#D3D3D3",
    preview_background="#101418",
    preview_text="#D6D6D6",
    scrollbar="rgba(120, 120, 120, 0.45)",
    scrollbar_hover="rgba(120, 120, 120, 0.70)",
    radius_sm=8,
    radius_md=12,
    radius_lg=18,
    spacing_sm=10,
    spacing_md=18,
    spacing_lg=28,
    badge_waiting=BadgeToken("#1f6feb", "#FFFFFF"),
    badge_success=BadgeToken("#138a36", "#FFFFFF"),
    badge_error=BadgeToken("#c42b1c", "#FFFFFF"),
    badge_offline=BadgeToken("#5d5a58", "#FFFFFF"),
)


DARK_TOKENS = DesignTokens(
    mode="dark",
    background="#0B1220",
    card_surface="#122033",
    card_border="rgba(144, 202, 249, 0.14)",
    card_shadow="rgba(0, 0, 0, 0.26)",
    hover_background="rgba(144, 202, 249, 0.08)",
    hover_border="rgba(144, 202, 249, 0.20)",
    primary="#90CAF9",
    primary_hover="#A6D8FA",
    text_primary="#D6E2F0",
    text_secondary="#93A4B7",
    panel_border="rgba(144, 202, 249, 0.14)",
    preview_background="#08101D",
    preview_text="#D6E2F0",
    scrollbar="rgba(144, 202, 249, 0.20)",
    scrollbar_hover="rgba(144, 202, 249, 0.34)",
    radius_sm=8,
    radius_md=12,
    radius_lg=18,
    spacing_sm=10,
    spacing_md=18,
    spacing_lg=28,
    badge_waiting=BadgeToken("#1A3A5C", "#90CAF9"),
    badge_success=BadgeToken("#0D3320", "#81C784"),
    badge_error=BadgeToken("#3D1410", "#EF5350"),
    badge_offline=BadgeToken("#14263D", "#93A4B7"),
)


def tokens_for_mode(mode: ThemeMode) -> DesignTokens:
    return DARK_TOKENS if mode == "dark" else LIGHT_TOKENS


def css_color_to_qcolor(value: str) -> QColor:
    """Convert a hex or rgba() CSS color string to QColor."""
    if value.startswith("rgba("):
        parts = value[5:-1].split(",")
        if len(parts) == 4:
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            a = round(float(parts[3].strip()) * 255)
            return QColor(r, g, b, a)
    return QColor(value)
