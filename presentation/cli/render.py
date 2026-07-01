"""
终端渲染工具：颜色、表格、分隔线等
"""

import os
import sys

# 自动检测是否支持彩色输出
_SUPPORTS_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
_FORCE_COLOR = os.environ.get("FORCE_COLOR", "")

COLOR_RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

COLOR_MAP = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "gray": "\033[90m",
    "bright_green": "\033[32;1m",
    "bright_red": "\033[31;1m",
    "bright_yellow": "\033[33;1m",
}


def _color(code: str, text: str) -> str:
    if not _color_enabled():
        return text
    return f"{COLOR_MAP.get(code, '')}{text}{COLOR_RESET}"


def _color_enabled() -> bool:
    return _SUPPORTS_COLOR or _FORCE_COLOR


def red(text: str) -> str:
    return _color("red", text)


def green(text: str) -> str:
    return _color("green", text)


def yellow(text: str) -> str:
    return _color("yellow", text)


def blue(text: str) -> str:
    return _color("blue", text)


def cyan(text: str) -> str:
    return _color("cyan", text)


def magenta(text: str) -> str:
    return _color("magenta", text)


def gray(text: str) -> str:
    return _color("gray", text)


def bold(text: str) -> str:
    if not _color_enabled():
        return text
    return f"{BOLD}{text}{COLOR_RESET}"


def dim(text: str) -> str:
    if not _color_enabled():
        return text
    return f"{DIM}{text}{COLOR_RESET}"


def bar(value: float, max_val: float, width: int = 20, color="green") -> str:
    """生成一个进度条风格的文本"""
    ratio = min(value / max_val, 1.0) if max_val > 0 else 0
    filled = int(width * ratio)
    empty = width - filled
    bar_char = _color(color, "█") if _color_enabled() else "#"
    empty_char = _color("gray", "░") if _color_enabled() else "-"
    return bar_char * filled + empty_char * empty


def divider(char: str = "─", width: int = 70, color: str = "gray") -> str:
    sep = _color(color, char * width) if _color_enabled() else char * width
    return sep


def section(title: str, color: str = "cyan") -> str:
    """生成分隔标题"""
    line = divider(width=70, color=color)
    return f"{line}\n{_color(color, '◆ ' + title)}\n{line}"


def row(cells: list, widths: list, colors: list = None) -> str:
    """渲染一行表格"""
    if colors is None:
        colors = ["white"] * len(cells)
    parts = []
    for cell, width, c in zip(cells, widths, colors):
        text = str(cell)
        if len(text) > width:
            text = text[: width - 2] + ".."
        aligned = f"{text:<{width}}"
        parts.append(_color(c, aligned))
    return "│ " + " │ ".join(parts) + " │"


def header_row(cells: list, widths: list, color: str = "blue") -> str:
    """渲染表头行"""
    parts = []
    for cell, width in zip(cells, widths):
        aligned = f"{cell:<{width}}"
        parts.append(_color(color, bold(aligned)))
    return "│ " + " │ ".join(parts) + " │"


def table_top(widths: list) -> str:
    corners = "┌" + "┬".join("─" * w for w in widths) + "┐"
    return corners


def table_mid(widths: list) -> str:
    sep = "├" + "┼".join("─" * w for w in widths) + "┤"
    return sep


def table_bot(widths: list) -> str:
    corners = "└" + "┴".join("─" * w for w in widths) + "┘"
    return corners


def box(text: str, width: int = 70, border_color: str = "cyan") -> str:
    """用边框包裹文本"""
    inner = text[: width - 4]
    top = _color(border_color, "┌" + "─" * (width - 2) + "┐") if _color_enabled() else f"+{'-'* (width-2)}+"
    bot = _color(border_color, "└" + "─" * (width - 2) + "┘") if _color_enabled() else f"+{'-'* (width-2)}+"
    inner_w = width - 2
    aligned = f"{inner:<{inner_w}}"
    return f"{top}\n{_color(border_color, '│')} {aligned} {_color(border_color, '│')}\n{bot}"


# 供外部直接使用的 console 对象
class Console:
    def section(self, title: str, color: str = "cyan") -> None:
        print(section(title, color))

    def divider(self, color: str = "gray") -> None:
        print(divider(color=color))

    def info(self, msg: str) -> None:
        print(f"  {gray('ℹ')}  {msg}")

    def success(self, msg: str) -> None:
        print(f"  {green('✓')}  {msg}")

    def warn(self, msg: str) -> None:
        print(f"  {yellow('⚠')}  {msg}")

    def error(self, msg: str) -> None:
        print(f"  {red('✗')}  {msg}")


console = Console()
