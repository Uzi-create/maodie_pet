from __future__ import annotations

import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from PySide6.QtCore import QObject, QPoint, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
    from PySide6.QtGui import (
        QAction,
        QActionGroup,
        QColor,
        QFont,
        QFontDatabase,
        QGuiApplication,
        QIcon,
        QImageReader,
        QLinearGradient,
        QMouseEvent,
        QMovie,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QPolygon,
        QRadialGradient,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QMenu,
        QProgressBar,
        QSystemTrayIcon,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print(
        "缺少 PySide6。本猫拒绝赤手空拳上班，请先运行：\n"
        "  python -m pip install -r requirements.txt"
    )
    raise SystemExit(1)

from codex_usage import CodexUsageError, CodexUsageReport, UsageWindow, fetch_codex_usage


APP_DIR = Path(__file__).resolve().parent
ASSET_DIR = APP_DIR / "assets"
IDLE_PATHS = (
    ASSET_DIR / "idle-sprite-v4.png",
    ASSET_DIR / "idle-sprite-v2.png",
    ASSET_DIR / "idle-sprite.png",
    ASSET_DIR / "idle.png",
)
STILL_PATHS = {
    "hiss": ASSET_DIR / "hiss-sprite.png",
}
MOVIE_PATHS = {
    "crawl": ASSET_DIR / "crawl.gif",
}

_FONT_FILES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
)
_FONTS_REGISTERED = False
_CJK_FONT_FAMILY = "Microsoft YaHei"


def _register_chinese_fonts() -> None:
    global _CJK_FONT_FAMILY, _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    selected_family: str | None = None
    for font_path in _FONT_FILES:
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families and selected_family is None:
                selected_family = families[0]
    if selected_family is not None:
        _CJK_FONT_FAMILY = selected_family
    _FONTS_REGISTERED = True


def _cjk_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(_CJK_FONT_FAMILY)
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


class SpeechBubble(QLabel):
    """Warm comic-style speech bubble with a small tail and soft shadow."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setContentsMargins(7, 3, 7, 9)
        self.setStyleSheet(
            "QLabel {"
            "  color: #35251d;"
            "  background: transparent;"
            "}"
        )
        self.setFont(_cjk_font(10, QFont.Weight.DemiBold))

    def _bubble_path(self, x_offset: float = 0.0, y_offset: float = 0.0) -> QPainterPath:
        body = QRectF(2 + x_offset, 2 + y_offset, self.width() - 4, self.height() - 11)
        path = QPainterPath()
        path.addRoundedRect(body, 10, 10)
        tail = QPainterPath()
        tail.moveTo(self.width() * 0.58 + x_offset, body.bottom() - 1)
        tail.lineTo(self.width() * 0.67 + x_offset, self.height() - 2 + y_offset)
        tail.lineTo(self.width() * 0.72 + x_offset, body.bottom() - 1)
        tail.closeSubpath()
        path.addPath(tail)
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(52, 32, 20, 62))
        painter.drawPath(self._bubble_path(1.2, 2.0))

        gradient = QLinearGradient(0, 1, 0, self.height() - 8)
        gradient.setColorAt(0.0, QColor(255, 253, 246, 250))
        gradient.setColorAt(1.0, QColor(249, 234, 209, 248))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(105, 69, 46, 235), 1.2))
        painter.drawPath(self._bubble_path())
        painter.end()

        super().paintEvent(event)


class PetScene(QWidget):
    """Low-key animated stage drawn behind the sprite."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._mode = "idle"
        self._phase = 0
        self._direction = 1

    def set_mode(self, mode: str, direction: int = 1) -> None:
        self._mode = mode
        self._direction = 1 if direction >= 0 else -1
        self._phase = 0
        self.update()

    def advance(self) -> None:
        if not self.isVisible():
            return
        self._phase = (self._phase + 1) % 720
        self.update()

    @staticmethod
    def _draw_paw(painter: QPainter, x: float, y: float, alpha: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(123, 79, 48, alpha))
        painter.drawEllipse(QRectF(x + 2.5, y + 4.0, 5.8, 4.8))
        painter.drawEllipse(QRectF(x, y + 0.8, 2.8, 3.2))
        painter.drawEllipse(QRectF(x + 3.2, y, 2.8, 3.2))
        painter.drawEllipse(QRectF(x + 6.4, y + 0.8, 2.8, 3.2))

    def _draw_ground(self, painter: QPainter, crawl: bool) -> None:
        rect = QRectF(5, 124, 120, 11) if crawl else QRectF(23, 123, 84, 13)
        centre = rect.center()
        gradient = QRadialGradient(centre, rect.width() / 2)
        gradient.setColorAt(0.0, QColor(71, 43, 27, 80 if crawl else 62))
        gradient.setColorAt(0.62, QColor(91, 55, 32, 35))
        gradient.setColorAt(1.0, QColor(91, 55, 32, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)

    def _draw_idle_scene(self, painter: QPainter) -> None:
        self._draw_ground(painter, crawl=False)

        # A barely-there woven mat gives the sitting pose a home without
        # turning the transparent pet into a rectangular wallpaper tile.
        painter.setBrush(QColor(211, 166, 106, 22))
        painter.setPen(QPen(QColor(139, 91, 54, 72), 0.9, Qt.PenStyle.DashLine))
        painter.drawEllipse(QRectF(18, 121, 94, 15))

        variant_span = 38
        variant = (self._phase // variant_span) % 3
        pulse = int(48 + 30 * (0.5 + 0.5 * math.sin(self._phase * 0.12)))
        if variant == 0:
            self._draw_paw(painter, 7, 113, pulse)
            self._draw_paw(painter, 113, 117, max(20, pulse - 18))
        elif variant == 1:
            angle = self._phase * 0.09
            x = 108 + math.cos(angle) * 8
            y = 61 + math.sin(angle * 1.7) * 6
            painter.setPen(QPen(QColor(181, 125, 55, 145), 1.0))
            painter.drawLine(round(x - 3), round(y - 2), round(x), round(y))
            painter.drawLine(round(x + 3), round(y - 2), round(x), round(y))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(239, 184, 73, 185))
            painter.drawEllipse(QRectF(x - 1.3, y - 1.3, 2.6, 2.6))
        else:
            painter.setFont(_cjk_font(10, QFont.Weight.Bold))
            painter.setPen(QColor(107, 76, 57, pulse + 45))
            lift = int((self._phase % variant_span) / 10)
            painter.drawText(107, 71 - lift, "Z")
            painter.setFont(_cjk_font(7, QFont.Weight.Bold))
            painter.drawText(116, 61 - lift, "z")

        # Slow golden dust motes keep the scene alive even between variants.
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (base_x, base_y) in enumerate(((13, 85), (118, 91), (10, 68))):
            offset = self._phase * (0.035 + index * 0.007) + index * 1.9
            x = base_x + math.sin(offset) * 3
            y = base_y - ((self._phase + index * 31) % 70) * 0.12
            alpha = int(40 + 36 * (0.5 + 0.5 * math.sin(offset * 1.8)))
            painter.setBrush(QColor(213, 159, 78, alpha))
            painter.drawEllipse(QRectF(x, y, 2.0, 2.0))

    def _draw_crawl_scene(self, painter: QPainter) -> None:
        self._draw_ground(painter, crawl=True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(116, 77, 52, 105), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        wave = math.sin(self._phase * 0.32) * 2
        if self._direction > 0:
            starts = (3, 10, 17)
            for index, start in enumerate(starts):
                y = 97 + index * 10 + wave
                painter.drawLine(start, round(y), start + 16 + index * 3, round(y))
            dust_x = 7
        else:
            starts = (127, 120, 113)
            for index, start in enumerate(starts):
                y = 97 + index * 10 + wave
                painter.drawLine(start, round(y), start - 16 - index * 3, round(y))
            dust_x = 114

        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            drift = (self._phase * (1.4 + index * 0.25) + index * 7) % 18
            x = dust_x - drift if self._direction > 0 else dust_x + drift
            y = 124 - index * 4 - abs(math.sin(self._phase * 0.18 + index)) * 3
            size = 5.5 - index
            painter.setBrush(QColor(151, 118, 83, 58 + index * 18))
            painter.drawEllipse(QRectF(x, y, size, size * 0.65))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._mode == "crawl":
            self._draw_crawl_scene(painter)
        else:
            self._draw_idle_scene(painter)


def _format_reset_time(timestamp: int | None) -> str:
    if timestamp is None:
        return "时间未知"
    reset = datetime.fromtimestamp(timestamp)
    seconds = max(0, int(timestamp - time.time()))
    if seconds < 60:
        relative = "不到 1 分钟"
    elif seconds < 3600:
        relative = f"约 {max(1, seconds // 60)} 分钟"
    elif seconds < 86400:
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        relative = f"约 {hours} 小时" + (f" {minutes} 分" if minutes else "")
    else:
        days, remainder = divmod(seconds, 86400)
        hours = remainder // 3600
        relative = f"约 {days} 天" + (f" {hours} 小时" if hours else "")
    return f"{reset:%m月%d日 %H:%M}（{relative}后）"


def _compact_tokens(value: int | None) -> str:
    if value is None:
        return "暂无 token 统计"
    if value >= 100_000_000:
        return f"累计 {value / 100_000_000:.2f} 亿 token"
    if value >= 10_000:
        return f"累计 {value / 10_000:.1f} 万 token"
    return f"累计 {value:,} token"


class UsageCard(QWidget):
    """Temporary account-usage card that visually points back to the pet."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(292, 226)

        self.panel = QFrame(self)
        self.panel.setObjectName("usagePanel")
        self.panel.setGeometry(8, 8, 276, 198)
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(22)
        shadow.setOffset(2, 4)
        shadow.setColor(QColor(41, 24, 14, 92))
        self.panel.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(15, 11, 15, 11)
        layout.setSpacing(3)

        header = QHBoxLayout()
        title = QLabel("老吴的 Codex 猫账本")
        title.setObjectName("usageTitle")
        self.plan_label = QLabel("PLAN")
        self.plan_label.setObjectName("planPill")
        self.plan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.plan_label)
        layout.addLayout(header)

        five_header = QHBoxLayout()
        five_title = QLabel("5 小时额度")
        five_title.setObjectName("limitTitle")
        self.five_percent = QLabel("等待老吴拨算盘")
        self.five_percent.setObjectName("limitPercent")
        five_header.addWidget(five_title)
        five_header.addStretch(1)
        five_header.addWidget(self.five_percent)
        layout.addLayout(five_header)
        self.five_bar = QProgressBar()
        self._prepare_bar(self.five_bar, "#d98745")
        layout.addWidget(self.five_bar)
        self.five_reset = QLabel("恢复：—")
        self.five_reset.setObjectName("resetText")
        layout.addWidget(self.five_reset)

        weekly_header = QHBoxLayout()
        weekly_title = QLabel("周额度")
        weekly_title.setObjectName("limitTitle")
        self.weekly_percent = QLabel("等待老吴拨算盘")
        self.weekly_percent.setObjectName("limitPercent")
        weekly_header.addWidget(weekly_title)
        weekly_header.addStretch(1)
        weekly_header.addWidget(self.weekly_percent)
        layout.addLayout(weekly_header)
        self.weekly_bar = QProgressBar()
        self._prepare_bar(self.weekly_bar, "#a56f4a")
        layout.addWidget(self.weekly_bar)
        self.weekly_reset = QLabel("重置：—")
        self.weekly_reset.setObjectName("resetText")
        layout.addWidget(self.weekly_reset)

        self.token_summary = QLabel("账本还没翻开")
        self.token_summary.setObjectName("tokenSummary")
        self.token_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.token_summary)

        self.setStyleSheet(
            "QFrame#usagePanel {"
            "  background: rgba(255, 250, 238, 250);"
            "  border: 1px solid #79513a;"
            "  border-radius: 16px;"
            "}"
            "QLabel { color: #3b2a20; background: transparent; }"
            "QLabel#usageTitle { }"
            "QLabel#planPill { color: #fff9eb; background: #8b593a;"
            "  border-radius: 7px; padding: 2px 8px; }"
            "QLabel#limitTitle { }"
            "QLabel#limitPercent { color: #7a5139; }"
            "QLabel#resetText { color: #77665b; }"
            "QLabel#tokenSummary { color: #604532; background: rgba(218, 190, 151, 70);"
            "  border-radius: 7px; padding: 3px 6px; }"
        )
        title.setFont(_cjk_font(14, QFont.Weight.Bold))
        self.plan_label.setFont(_cjk_font(9, QFont.Weight.Bold))
        five_title.setFont(_cjk_font(11, QFont.Weight.Bold))
        self.five_percent.setFont(_cjk_font(10, QFont.Weight.DemiBold))
        self.five_reset.setFont(_cjk_font(9))
        weekly_title.setFont(_cjk_font(11, QFont.Weight.Bold))
        self.weekly_percent.setFont(_cjk_font(10, QFont.Weight.DemiBold))
        self.weekly_reset.setFont(_cjk_font(9))
        self.token_summary.setFont(_cjk_font(9, QFont.Weight.DemiBold))

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    @staticmethod
    def _prepare_bar(bar: QProgressBar, colour: str) -> None:
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(9)
        bar.setStyleSheet(
            "QProgressBar { border: none; border-radius: 4px; background: #e8dccb; }"
            f"QProgressBar::chunk {{ border-radius: 4px; background: {colour}; }}"
        )

    @staticmethod
    def _set_window(
        window: UsageWindow | None,
        percent_label: QLabel,
        bar: QProgressBar,
        reset_label: QLabel,
        reset_prefix: str,
    ) -> None:
        if window is None:
            percent_label.setText("暂无数据")
            bar.setValue(0)
            reset_label.setText(f"{reset_prefix}：未知")
            return
        used = int(round(window.used_percent))
        remaining = max(0, 100 - used)
        percent_label.setText(f"剩余 {remaining}% · 已用 {used}%")
        bar.setValue(remaining)
        reset_label.setText(f"{reset_prefix}：{_format_reset_time(window.resets_at)}")

    def show_report(self, report: CodexUsageReport, pet: QWidget) -> None:
        self.plan_label.setText((report.plan_type or "未知计划").upper())
        self._set_window(report.five_hour, self.five_percent, self.five_bar, self.five_reset, "恢复")
        self._set_window(report.weekly, self.weekly_percent, self.weekly_bar, self.weekly_reset, "重置")

        footer = _compact_tokens(report.lifetime_tokens)
        if report.reset_credits is not None:
            footer += f"  ·  重置券 {report.reset_credits} 张"
        self.token_summary.setText(footer)
        self._place_near_pet(pet)
        self.show()
        self.raise_()
        self._hide_timer.start(20_000)

    def _place_near_pet(self, pet: QWidget) -> None:
        pet_rect = pet.frameGeometry()
        screen = QGuiApplication.screenAt(pet_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.move(max(8, pet.x() - self.width() + pet.width()), max(8, pet.y() - self.height()))
            return
        area = screen.availableGeometry()
        x = pet_rect.right() - self.width() + 20
        # Leave a real gap above the speech bubble. Near the top edge, put the
        # ledger below the whole pet window instead of clamping it onto the cat.
        above_y = pet_rect.top() - self.height() - 10
        below_y = pet_rect.bottom() + 10
        y = above_y if above_y >= area.top() + 6 else below_y
        x = max(area.left() + 6, min(x, area.right() - self.width() - 6))
        y = max(area.top() + 6, min(y, area.bottom() - self.height() - 6))
        self.move(x, y)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tail = QPainterPath()
        tail.moveTo(self.width() - 72, self.height() - 23)
        tail.lineTo(self.width() - 42, self.height() - 3)
        tail.lineTo(self.width() - 48, self.height() - 28)
        tail.closeSubpath()
        painter.setBrush(QColor(255, 250, 238, 250))
        painter.setPen(QPen(QColor(121, 81, 58), 1.0))
        painter.drawPath(tail)

    def mousePressEvent(self, event) -> None:
        self.hide()
        event.accept()


class UsageWorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class UsageWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = UsageWorkerSignals()

    def run(self) -> None:
        try:
            self.signals.succeeded.emit(fetch_codex_usage())
        except CodexUsageError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - keep the pet alive on surprises
            self.signals.failed.emit(f"查账时摔了一跤：{exc}")


class MaodiePet(QWidget):
    """A small, transparent desktop pet window."""

    WINDOW_WIDTH = 130
    WINDOW_HEIGHT = 140
    PET_SIZE = 98
    CRAWL_WIDTH = 136
    CRAWL_HEIGHT = 68
    PATROL_INTERVALS = (
        (10_000, "快速：每 10 秒"),
        (60_000, "每 1 分钟"),
        (120_000, "每 2 分钟"),
        (300_000, "每 5 分钟"),
        (None, "暂停自动巡查"),
    )

    CLICK_LINES = (
        "哈！！",
        "哈！！",
        "哈！！！",
        "哈！哈！！",
        "哈——！！",
        "老吴老吴老吴！",
        "老吴！哈！！",
        "爪拿开！哈！！",
        "哈！！莫挨老子！",
    )
    RANDOM_LINES = (
        "哈！！",
        "哈！！！",
        "老吴老吴老吴……",
        "哈！老吴！哈！！",
        "工作了吗？就敢看我。",
        "我在巡视这个破桌面。",
        "别卷了，卷也没猫条。",
        "今天也要体面地摸鱼。",
        "看什么，本猫自带置顶。",
        "CPU 在烧，我在乘凉。",
    )
    DRAG_LINES = (
        "哈！！",
        "哈！！！",
        "哈！哈！哈！！",
        "老吴老吴老吴！",
        "放开！哈！！",
        "爪不沾地了！哈！！",
    )

    def __init__(self) -> None:
        super().__init__()
        _register_chinese_fonts()

        self._always_on_top = True
        self._scene_enabled = True
        self._patrol_interval_ms: int | None = 60_000
        self._quitting = False
        self._cleaned_up = False
        self._usage_loading = False
        self._usage_worker: UsageWorker | None = None
        self._dragging = False
        self._moved_since_press = False
        self._drag_visual_started = False
        self._drag_visual_phase = 0
        self._drag_offset = QPoint()
        self._press_global = QPoint()

        self._action_name: str | None = None
        self._action_started_at = 0.0
        self._action_duration = 0.0
        self._action_origin = QPoint()
        self._action_target = QPoint()

        self._visual_state = "idle"
        self._active_movie: QMovie | None = None
        self._one_shot_state: str | None = None
        self._one_shot_last_frame = -1
        self._one_shot_seen_progress = False
        self._one_shot_finish_pending = False

        self.setWindowTitle("圆头耄耋")
        self.setFixedSize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.scene = PetScene(self)
        self.pet_label = QLabel(self)
        self.pet_label.setGeometry(
            (self.WINDOW_WIDTH - self.PET_SIZE) // 2,
            self.WINDOW_HEIGHT - self.PET_SIZE - 5,
            self.PET_SIZE,
            self.PET_SIZE,
        )
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pet_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pet_label_origin = self.pet_label.pos()
        self.scene.lower()

        self.bubble = SpeechBubble(self)
        self.bubble.setGeometry(5, 1, self.WINDOW_WIDTH - 10, 50)
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.bubble.hide()
        self._usage_card = UsageCard()

        self._idle_pixmap, self._using_placeholder = self._load_idle_pixmap()
        self._state_pixmaps = self._load_state_pixmaps()
        self._movies: dict[str, QMovie] = {}
        self._load_movies()

        self._one_shot_timer = QTimer(self)
        self._one_shot_timer.setSingleShot(True)
        self._one_shot_timer.timeout.connect(self._finish_one_shot)
        self._show_idle()

        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.bubble.hide)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._animate_action)

        self._drag_visual_timer = QTimer(self)
        self._drag_visual_timer.setInterval(70)
        self._drag_visual_timer.timeout.connect(self._animate_drag_visual)

        self._scene_timer = QTimer(self)
        self._scene_timer.setInterval(90)
        self._scene_timer.timeout.connect(self.scene.advance)
        self._scene_timer.start()

        self._auto_action_timer = QTimer(self)
        self._auto_action_timer.setSingleShot(True)
        self._auto_action_timer.timeout.connect(self._on_auto_action)

        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_visibility_action: QAction | None = None
        self._tray_top_action: QAction | None = None
        self._tray_scene_action: QAction | None = None
        self._tray_patrol_actions: dict[int | None, QAction] = {}
        self._create_tray()

        app = QApplication.instance()
        if app is not None:
            app.screenRemoved.connect(lambda _screen: QTimer.singleShot(0, self.constrain_to_screen))
            app.aboutToQuit.connect(self._cleanup)

    def _apply_window_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _load_idle_pixmap(self) -> tuple[QPixmap, bool]:
        """Load the completed sprite, then fall back without crashing."""
        for path in IDLE_PATHS:
            if not path.is_file():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap, False

        # A missing idle image should not make an otherwise valid animation pack
        # unusable. Reuse the first readable GIF frame as the static fallback.
        for path in MOVIE_PATHS.values():
            if not path.is_file():
                continue
            reader = QImageReader(str(path))
            frame = reader.read()
            if not frame.isNull():
                return QPixmap.fromImage(frame), False

        return self._draw_placeholder_cat(), True

    def _load_state_pixmaps(self) -> dict[str, QPixmap]:
        pixmaps: dict[str, QPixmap] = {}
        for state, path in STILL_PATHS.items():
            if not path.is_file():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                pixmaps[state] = pixmap
        return pixmaps

    def _load_movies(self) -> None:
        """Create every QMovie once and keep it alive for the whole app lifetime."""
        for state, path in MOVIE_PATHS.items():
            if not path.is_file():
                continue

            movie = QMovie(str(path))
            movie.setParent(self)
            movie.setCacheMode(QMovie.CacheMode.CacheAll)
            if not movie.isValid():
                movie.deleteLater()
                continue

            source_size = QImageReader(str(path)).size()
            if source_size.isValid():
                target_box = (
                    QSize(self.CRAWL_WIDTH, self.CRAWL_HEIGHT)
                    if state == "crawl"
                    else QSize(self.PET_SIZE, self.PET_SIZE)
                )
                movie.setScaledSize(
                    source_size.scaled(
                        target_box,
                        Qt.AspectRatioMode.KeepAspectRatio,
                    )
                )

            # Signals are wired exactly once here. Playback only rewinds/restarts
            # the existing object, so repeated clicks cannot multiply callbacks.
            movie.frameChanged.connect(
                lambda frame_number, movie_state=state: self._on_movie_frame_changed(
                    movie_state, frame_number
                )
            )
            movie.finished.connect(
                lambda movie_state=state: self._on_movie_finished(movie_state)
            )
            self._movies[state] = movie

    def _set_pet_box(self, state: str) -> None:
        if state == "crawl":
            width, height = self.CRAWL_WIDTH, self.CRAWL_HEIGHT
        else:
            width = height = self.PET_SIZE
        self.pet_label.setGeometry(
            (self.WINDOW_WIDTH - width) // 2,
            self.WINDOW_HEIGHT - height - 5,
            width,
            height,
        )
        self._pet_label_origin = self.pet_label.pos()

    def _stop_active_movie(self) -> None:
        if self._active_movie is not None:
            self._active_movie.stop()
        self._active_movie = None
        self._one_shot_timer.stop()
        self._one_shot_state = None
        self._one_shot_last_frame = -1
        self._one_shot_seen_progress = False
        self._one_shot_finish_pending = False

    def _show_idle(self) -> None:
        self._stop_active_movie()
        self._visual_state = "idle"
        self._set_pet_box("idle")
        self.scene.set_mode("idle")
        self.pet_label.clear()
        self.pet_label.setPixmap(
            self._idle_pixmap.scaled(
                self.PET_SIZE,
                self.PET_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _play_movie(self, state: str, *, once: bool, fallback_ms: int = 2600) -> bool:
        """Play one cached movie; unavailable/corrupt assets degrade to idle."""
        movie = self._movies.get(state)
        if movie is None or not movie.isValid():
            self._show_idle()
            return False

        self._stop_active_movie()
        self._visual_state = state
        self._set_pet_box(state)
        direction = 1
        if state == "crawl" and self._action_target.x() < self._action_origin.x():
            direction = -1
        self.scene.set_mode(state, direction)
        self._active_movie = movie
        self._one_shot_state = state if once else None
        self._one_shot_last_frame = -1
        self._one_shot_seen_progress = False
        self._one_shot_finish_pending = False

        movie.stop()
        movie.jumpToFrame(0)
        self.pet_label.clear()
        self.pet_label.setMovie(movie)
        movie.start()

        # Some malformed GIFs do not expose a useful final frame or finished
        # signal. This watchdog guarantees that a one-shot returns to idle.
        if once:
            self._one_shot_timer.start(fallback_ms)
        return True

    def _show_still_state(self, state: str, duration_ms: int) -> bool:
        """Show a completed transparent pose, then return to idle."""
        pixmap = self._state_pixmaps.get(state)
        if pixmap is None or pixmap.isNull():
            self._show_idle()
            return False

        self._stop_active_movie()
        self._visual_state = state
        self._set_pet_box(state)
        self.scene.set_mode(state)
        self._one_shot_state = state
        self.pet_label.clear()
        self.pet_label.setPixmap(
            pixmap.scaled(
                self.PET_SIZE,
                self.PET_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._one_shot_timer.start(duration_ms)
        return True

    def _begin_drag_visual(self) -> None:
        if self._drag_visual_started:
            return
        self._drag_visual_started = True
        self._drag_visual_phase = 0
        self._stop_active_movie()
        self._visual_state = "drag"
        self._set_pet_box("drag")
        self.scene.set_mode("drag")

        pixmap = self._state_pixmaps.get("hiss", self._idle_pixmap)
        self.pet_label.clear()
        self.pet_label.setPixmap(
            pixmap.scaled(
                self.PET_SIZE,
                self.PET_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.show_bubble(random.choice(self.DRAG_LINES), 1300)
        self._drag_visual_timer.start()

    def _animate_drag_visual(self) -> None:
        if not self._drag_visual_started:
            self._drag_visual_timer.stop()
            return
        offsets = ((-2, 0), (2, -1), (-2, -1), (2, 0), (0, -2), (0, 0))
        dx, dy = offsets[self._drag_visual_phase % len(offsets)]
        self._drag_visual_phase += 1
        self.pet_label.move(self._pet_label_origin + QPoint(dx, dy))

    def _end_drag_visual(self) -> None:
        self._drag_visual_timer.stop()
        self._drag_visual_started = False
        self._drag_visual_phase = 0
        self.pet_label.move(self._pet_label_origin)
        if self._visual_state == "drag":
            self._show_idle()

    def _play_visual_state(
        self,
        state: str,
        *,
        once: bool,
        fallback_ms: int,
    ) -> bool:
        if state in self._state_pixmaps:
            return self._show_still_state(state, fallback_ms)
        return self._play_movie(state, once=once, fallback_ms=fallback_ms)

    def _on_movie_frame_changed(self, state: str, frame_number: int) -> None:
        if self._visual_state != state or self._one_shot_state != state:
            return

        movie = self._movies.get(state)
        if movie is None:
            return

        if frame_number > 0:
            self._one_shot_seen_progress = True
        looped = (
            self._one_shot_seen_progress
            and self._one_shot_last_frame >= 0
            and frame_number < self._one_shot_last_frame
        )
        self._one_shot_last_frame = frame_number

        frame_count = movie.frameCount()
        reached_last = frame_count > 0 and frame_number >= frame_count - 1
        if (looped or reached_last) and not self._one_shot_finish_pending:
            self._one_shot_finish_pending = True
            # Leave the last frame on screen long enough to be painted.
            self._one_shot_timer.start(max(35, movie.nextFrameDelay()))

    def _on_movie_finished(self, state: str) -> None:
        if self._visual_state == state and self._one_shot_state == state:
            self._finish_one_shot()
        elif state == "crawl" and self._visual_state == "crawl":
            movie = self._movies.get(state)
            if movie is not None:
                movie.start()

    def _finish_one_shot(self) -> None:
        expected_state = self._one_shot_state
        if expected_state is not None and self._visual_state == expected_state:
            self._show_idle()

    @staticmethod
    def _draw_placeholder_cat() -> QPixmap:
        """Draw a visible grumpy orange cat when no external asset exists."""
        size = 512
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outline = QColor("#5d3828")
        orange = QColor("#d98635")
        light_orange = QColor("#efa758")
        cream = QColor("#f6d29c")

        painter.setPen(QPen(outline, 17, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(orange)
        painter.drawPolygon(QPolygon([QPoint(91, 197), QPoint(111, 51), QPoint(218, 136)]))
        painter.drawPolygon(QPolygon([QPoint(294, 136), QPoint(401, 51), QPoint(421, 197)]))

        painter.setBrush(QColor("#efaa72"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygon([QPoint(119, 136), QPoint(128, 85), QPoint(177, 137)]))
        painter.drawPolygon(QPolygon([QPoint(335, 137), QPoint(384, 85), QPoint(393, 136)]))

        painter.setPen(QPen(outline, 18))
        painter.setBrush(orange)
        painter.drawEllipse(49, 102, 414, 370)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(light_orange)
        painter.drawEllipse(82, 136, 348, 284)

        painter.setPen(QPen(outline, 15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(193, 234, 135, 217)
        painter.drawLine(319, 234, 377, 217)
        painter.drawLine(174, 274, 216, 279)
        painter.drawLine(338, 274, 296, 279)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(cream)
        painter.drawEllipse(150, 302, 115, 94)
        painter.drawEllipse(247, 302, 115, 94)

        painter.setBrush(outline)
        painter.drawPolygon(QPolygon([QPoint(231, 323), QPoint(281, 323), QPoint(256, 351)]))

        painter.setPen(QPen(outline, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(256, 351, 256, 369)
        painter.drawLine(256, 369, 229, 382)
        painter.drawLine(256, 369, 283, 382)

        painter.setPen(QPen(outline, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(222, 139, 203, 191)
        painter.drawLine(256, 132, 256, 190)
        painter.drawLine(290, 139, 309, 191)

        painter.setPen(QPen(QColor(255, 248, 229, 210), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(143, 168, 174, 148)

        painter.end()
        return canvas

    def place_near_bottom_right(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(30, 30)
            return
        area = screen.availableGeometry()
        self.move(
            area.x() + area.width() - self.width() - 14,
            area.y() + area.height() - self.height() - 9,
        )

    def start(self) -> None:
        self.place_near_bottom_right()
        self.show()
        self.raise_()
        self._schedule_auto_action()
        if self._using_placeholder:
            QTimer.singleShot(
                350,
                lambda: self.show_bubble("素材还没到，本猫先素颜上班。", 3000),
            )

    def _create_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        # QSystemTrayIcon does not own its context menu, so retain it explicitly.
        self._tray_menu = QMenu(self)
        menu = self._tray_menu
        self._tray_visibility_action = QAction("隐藏桌宠", self)
        self._tray_visibility_action.triggered.connect(self.toggle_visibility)
        menu.addAction(self._tray_visibility_action)

        random_action = QAction("随机动作", self)
        random_action.triggered.connect(self.trigger_random_action)
        menu.addAction(random_action)

        self._add_patrol_menu(menu, persistent=True)

        usage_action = QAction("老吴查账（Codex）", self)
        usage_action.triggered.connect(self.show_codex_usage)
        menu.addAction(usage_action)

        self._tray_scene_action = QAction("桌面小舞台", self)
        self._tray_scene_action.setCheckable(True)
        self._tray_scene_action.setChecked(self._scene_enabled)
        self._tray_scene_action.toggled.connect(self.set_scene_enabled)
        menu.addAction(self._tray_scene_action)

        self._tray_top_action = QAction("始终置顶", self)
        self._tray_top_action.setCheckable(True)
        self._tray_top_action.setChecked(self._always_on_top)
        self._tray_top_action.toggled.connect(self.set_always_on_top)
        menu.addAction(self._tray_top_action)
        menu.addSeparator()

        quit_action = QAction("退出耄耋", self)
        quit_action.triggered.connect(self.quit_pet)
        menu.addAction(quit_action)

        self._tray = QSystemTrayIcon(QIcon(self._idle_pixmap), self)
        self._tray.setToolTip("圆头耄耋：正在盯着你")
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _add_patrol_menu(self, menu: QMenu, *, persistent: bool = False) -> None:
        patrol_menu = menu.addMenu("巡查频率")
        group = QActionGroup(patrol_menu)
        group.setExclusive(True)
        actions: dict[int | None, QAction] = {}
        for interval_ms, label in self.PATROL_INTERVALS:
            action = patrol_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(interval_ms == self._patrol_interval_ms)
            action.triggered.connect(
                lambda checked, value=interval_ms: checked
                and self.set_patrol_interval(value)
            )
            group.addAction(action)
            actions[interval_ms] = action
        if persistent:
            self._tray_patrol_actions = actions

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.toggle_visibility()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
            self._usage_card.hide()
            if self._tray_visibility_action is not None:
                self._tray_visibility_action.setText("显示桌宠")
        else:
            self.show()
            self.constrain_to_screen()
            self.raise_()
            self.activateWindow()
            if self._tray_visibility_action is not None:
                self._tray_visibility_action.setText("隐藏桌宠")

    def set_always_on_top(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._always_on_top:
            return

        position = self.pos()
        was_visible = self.isVisible()
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self._tray_top_action is not None:
            self._tray_top_action.blockSignals(True)
            self._tray_top_action.setChecked(enabled)
            self._tray_top_action.blockSignals(False)
        if was_visible:
            self.show()
            self.move(self._clamped_position(position))
            self.raise_()
        self.show_bubble("置顶：开。谁也别想压我。" if enabled else "置顶：关。暂且低调。")

    def set_scene_enabled(self, enabled: bool) -> None:
        self._scene_enabled = bool(enabled)
        self.scene.setVisible(self._scene_enabled)
        if self._tray_scene_action is not None:
            self._tray_scene_action.blockSignals(True)
            self._tray_scene_action.setChecked(self._scene_enabled)
            self._tray_scene_action.blockSignals(False)
        self.show_bubble(
            "小舞台开演。别眨眼。" if self._scene_enabled else "布景撤了，只看本猫。"
        )

    def set_patrol_interval(self, interval_ms: int | None) -> None:
        self._patrol_interval_ms = interval_ms
        for value, action in self._tray_patrol_actions.items():
            action.blockSignals(True)
            action.setChecked(value == interval_ms)
            action.blockSignals(False)
        self._schedule_auto_action()
        if interval_ms is None:
            self.show_bubble("自动巡查暂停。本猫申请带薪坐牢。", 3000)
        else:
            if interval_ms < 60_000:
                cadence = f"{interval_ms // 1000} 秒"
            else:
                cadence = f"{interval_ms // 60_000} 分钟"
            self.show_bubble(f"每 {cadence}巡查一次。别催。", 2800)

    def show_bubble(self, text: str, duration_ms: int = 2300) -> None:
        self.bubble.setText(text)
        self.bubble.show()
        self.bubble.raise_()
        self._bubble_timer.start(duration_ms)

    def trigger_random_action(self) -> None:
        if self._dragging:
            return
        self.show_bubble(random.choice(self.RANDOM_LINES))
        self._start_action("stroll")
        self._play_movie("crawl", once=False)

    def show_codex_usage(self) -> None:
        if self._dragging:
            return
        if self._usage_loading:
            self.show_bubble("账还在算。催什么催，算盘又不是显卡。", 2800)
            return

        self._usage_loading = True
        self.show_bubble("把 Codex 账本拿来。本猫开始审计。", 3200)
        self._start_action("shake")
        worker = UsageWorker()
        worker.signals.succeeded.connect(self._on_codex_usage_loaded)
        worker.signals.failed.connect(self._on_codex_usage_failed)
        self._usage_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_codex_usage_loaded(self, report: CodexUsageReport) -> None:
        self._usage_loading = False
        self._usage_worker = None
        if self._cleaned_up:
            return
        self._usage_card.show_report(report, self)
        self.show_bubble("账摊这儿了。20 秒后销毁证据。", 3000)

    def _on_codex_usage_failed(self, message: str) -> None:
        self._usage_loading = False
        self._usage_worker = None
        if self._cleaned_up:
            return
        self.show_bubble("账本打不开。Codex 又在装死。", 3600)
        if self._tray is not None:
            self._tray.showMessage(
                "老吴查账失败",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                4500,
            )

    def _start_action(self, name: str) -> None:
        self._finish_action(reset_position=True)
        self._action_name = name
        self._action_started_at = time.monotonic()
        self._action_origin = self.pos()
        self._action_target = self._action_origin

        if name == "bounce":
            self._action_duration = 0.85
        elif name == "shake":
            self._action_duration = 0.65
        else:
            self._action_duration = 1.45
            raw_target = QPoint(
                self._action_origin.x() + random.randint(-85, 85),
                self._action_origin.y() + random.randint(-18, 18),
            )
            self._action_target = self._clamped_position(raw_target)

        self._animation_timer.start()

    def _animate_action(self) -> None:
        if self._action_name is None:
            self._animation_timer.stop()
            return

        elapsed = time.monotonic() - self._action_started_at
        progress = min(1.0, elapsed / self._action_duration)
        origin = self._action_origin

        if self._action_name == "bounce":
            y_offset = -round(math.sin(math.pi * progress) * 20)
            position = QPoint(origin.x(), origin.y() + y_offset)
        elif self._action_name == "shake":
            decay = 1.0 - progress
            x_offset = round(math.sin(progress * math.pi * 12) * 6 * decay)
            y_offset = round(math.sin(progress * math.pi * 6) * 2 * decay)
            position = QPoint(origin.x() + x_offset, origin.y() + y_offset)
        else:
            smooth = progress * progress * (3.0 - 2.0 * progress)
            x = round(origin.x() + (self._action_target.x() - origin.x()) * smooth)
            y = round(origin.y() + (self._action_target.y() - origin.y()) * smooth)
            bob = round(abs(math.sin(progress * math.pi * 6)) * 3)
            position = QPoint(x, y - bob)

        self.move(self._clamped_position(position))
        if progress >= 1.0:
            self._finish_action(reset_position=True)

    def _finish_action(self, reset_position: bool) -> None:
        if self._action_name is None:
            return
        finished_action = self._action_name
        final_position = self._action_target if finished_action == "stroll" else self._action_origin
        self._animation_timer.stop()
        self._action_name = None
        if reset_position:
            self.move(self._clamped_position(final_position))
        if finished_action == "stroll" and self._visual_state == "crawl":
            self._show_idle()

    def _schedule_auto_action(self) -> None:
        self._auto_action_timer.stop()
        if self._patrol_interval_ms is not None:
            self._auto_action_timer.start(self._patrol_interval_ms)

    def _on_auto_action(self) -> None:
        if (
            self.isVisible()
            and not self._dragging
            and self._action_name is None
            and self._visual_state == "idle"
        ):
            self.trigger_random_action()
        self._schedule_auto_action()

    def _screen_for_point(self, point: QPoint):
        screen = QGuiApplication.screenAt(point)
        if screen is not None:
            return screen

        screens = QGuiApplication.screens()
        if not screens:
            return None

        def distance_squared(candidate) -> int:
            area = candidate.availableGeometry()
            dx = max(area.left() - point.x(), 0, point.x() - area.right())
            dy = max(area.top() - point.y(), 0, point.y() - area.bottom())
            return dx * dx + dy * dy

        return min(screens, key=distance_squared)

    def _clamped_position(self, position: QPoint, reference: QPoint | None = None) -> QPoint:
        if reference is None:
            reference = QPoint(
                position.x() + self.width() // 2,
                position.y() + self.height() // 2,
            )
        screen = self._screen_for_point(reference)
        if screen is None:
            return position

        area = screen.availableGeometry()
        min_x = area.x()
        min_y = area.y()
        max_x = max(min_x, area.x() + area.width() - self.width())
        max_y = max(min_y, area.y() + area.height() - self.height())
        return QPoint(
            max(min_x, min(position.x(), max_x)),
            max(min_y, min(position.y(), max_y)),
        )

    def constrain_to_screen(self) -> None:
        self.move(self._clamped_position(self.pos()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._finish_action(reset_position=True)
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            self._dragging = True
            self._moved_since_press = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if (current - self._press_global).manhattanLength() > 5:
                if not self._moved_since_press:
                    self._moved_since_press = True
                    self._begin_drag_visual()
            desired = current - self._drag_offset
            self.move(self._clamped_position(desired, current))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if self._moved_since_press:
                self._end_drag_visual()
                self.constrain_to_screen()
                self._start_action("bounce")
            else:
                self.show_bubble(random.choice(self.CLICK_LINES))
                self._start_action("shake")
                self._play_visual_state("hiss", once=True, fallback_ms=1150)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)

        top_action = menu.addAction("始终置顶")
        top_action.setCheckable(True)
        top_action.setChecked(self._always_on_top)
        top_action.toggled.connect(self.set_always_on_top)

        random_action = menu.addAction("随机动作")
        random_action.triggered.connect(self.trigger_random_action)

        self._add_patrol_menu(menu)

        usage_action = menu.addAction("老吴查账（Codex）")
        usage_action.triggered.connect(self.show_codex_usage)

        scene_action = menu.addAction("桌面小舞台")
        scene_action.setCheckable(True)
        scene_action.setChecked(self._scene_enabled)
        scene_action.toggled.connect(self.set_scene_enabled)
        menu.addSeparator()

        quit_action = menu.addAction("退出耄耋")
        quit_action.triggered.connect(self.quit_pet)
        menu.exec(event.globalPos())

    def quit_pet(self) -> None:
        self._quitting = True
        self._cleanup()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self._animation_timer.stop()
        self._auto_action_timer.stop()
        self._bubble_timer.stop()
        self._one_shot_timer.stop()
        self._drag_visual_timer.stop()
        self._scene_timer.stop()
        self._stop_active_movie()
        self._usage_card.hide()
        for movie in self._movies.values():
            movie.stop()
        if self._tray is not None:
            self._tray.hide()

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
            return
        if self._tray is not None and self._tray.isVisible():
            self.hide()
            self._usage_card.hide()
            if self._tray_visibility_action is not None:
                self._tray_visibility_action.setText("显示桌宠")
            self._tray.showMessage(
                "圆头耄耋",
                "本猫躲进托盘了，双击图标即可召回。",
                QSystemTrayIcon.MessageIcon.Information,
                1800,
            )
            event.ignore()
            return
        self._quitting = True
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("圆头耄耋桌宠")
    app.setOrganizationName("MaodiePet")
    app.setQuitOnLastWindowClosed(False)

    pet = MaodiePet()
    pet.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
