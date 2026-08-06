from pathlib import Path
from typing import Optional, Tuple

from PyQt5.QtCore import QElapsedTimer, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtMultimedia import (
    QAbstractVideoBuffer,
    QAbstractVideoSurface,
    QMediaContent,
    QMediaPlayer,
    QVideoFrame,
)
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel
from qfluentwidgets.multimedia import SimpleMediaPlayBar

from videocaptioner.core.entities import SupportedVideoFormats

VIDEO_PREVIEW_SUFFIXES = {f".{item.value}" for item in SupportedVideoFormats}


def format_media_time(milliseconds: int) -> str:
    """Format a media position without letting invalid values leak into the UI."""
    total_seconds = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def select_preview_canvas_size(
    forced_canvas: Optional[Tuple[int, int]],
    has_video: bool,
    source_changed: bool,
    native_size: Optional[Tuple[int, int]],
    poster_size: Optional[Tuple[int, int]],
    current_size: Tuple[int, int],
) -> Tuple[int, int]:
    """Choose the logical canvas while media metadata loads asynchronously."""
    if forced_canvas:
        return forced_canvas
    if has_video and not source_changed and native_size:
        return native_size
    if poster_size:
        return poster_size
    return native_size or current_size


def select_preview_view_size(
    canvas_size: Tuple[int, int],
    available_size: Tuple[int, int],
) -> Tuple[int, int]:
    """Aspect-fit the visible canvas without padding inside the black view."""
    canvas_width, canvas_height = canvas_size
    available_width = max(1, int(available_size[0]))
    available_height = max(1, int(available_size[1]))
    if canvas_width <= 0 or canvas_height <= 0:
        return available_width, available_height
    scale = min(
        available_width / canvas_width,
        available_height / canvas_height,
    )
    return (
        max(1, round(canvas_width * scale)),
        max(1, round(canvas_height * scale)),
    )


class _SoftwareVideoSurface(QAbstractVideoSurface):
    """Convert Qt Multimedia frames into images that QGraphicsScene can paint."""

    imageAvailable = pyqtSignal(QImage)
    _FRAME_INTERVAL_MS = 33

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_clock = QElapsedTimer()
        self._frame_clock.start()
        self.resetFrameThrottle()

    def resetFrameThrottle(self) -> None:
        self._last_frame_ms = -self._FRAME_INTERVAL_MS

    def start(self, surface_format) -> bool:
        self.resetFrameThrottle()
        return super().start(surface_format)

    def supportedPixelFormats(
        self, handle_type=QAbstractVideoBuffer.NoHandle
    ) -> list[QVideoFrame.PixelFormat]:
        if handle_type != QAbstractVideoBuffer.NoHandle:
            return []
        return [
            QVideoFrame.Format_ARGB32,
            QVideoFrame.Format_ARGB32_Premultiplied,
            QVideoFrame.Format_RGB32,
            QVideoFrame.Format_RGB24,
            QVideoFrame.Format_RGB565,
            QVideoFrame.Format_RGB555,
        ]

    def present(self, frame: QVideoFrame) -> bool:
        now = self._frame_clock.elapsed()
        if now - self._last_frame_ms < self._FRAME_INTERVAL_MS:
            return True
        if not frame.isValid() or not frame.map(QAbstractVideoBuffer.ReadOnly):
            return False
        try:
            image_format = QVideoFrame.imageFormatFromPixelFormat(frame.pixelFormat())
            if image_format == QImage.Format_Invalid:
                return False
            bits = frame.bits()
            bits.setsize(frame.mappedBytes())
            image = QImage(
                bits,
                frame.width(),
                frame.height(),
                frame.bytesPerLine(),
                image_format,
            ).copy()
        finally:
            frame.unmap()
        if image.isNull():
            return False
        self._last_frame_ms = now
        self.imageAvailable.emit(image)
        return True


class SubtitleVideoPreview(QWidget):
    """Video/image preview with a transparent subtitle layer."""

    canvasSizeChanged = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_path = ""
        self._poster_path = ""
        self._forced_canvas: Optional[Tuple[int, int]] = None
        self._canvas_size = (1280, 720)
        self._poster_pixmap = QPixmap()
        self._video_pixmap = QPixmap()
        self._native_size: Optional[Tuple[int, int]] = None
        self._has_started = False

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.view.setStyleSheet(
            "QGraphicsView { background: black; border: 0; border-radius: 8px; }"
        )

        self.videoItem = QGraphicsPixmapItem()
        self.videoItem.setTransformationMode(Qt.SmoothTransformation)
        self.videoItem.setZValue(0)
        self.scene.addItem(self.videoItem)

        self.posterItem = QGraphicsPixmapItem()
        self.posterItem.setTransformationMode(Qt.SmoothTransformation)
        self.posterItem.setZValue(1)
        self.scene.addItem(self.posterItem)

        self.subtitleItem = QGraphicsPixmapItem()
        self.subtitleItem.setTransformationMode(Qt.SmoothTransformation)
        self.subtitleItem.setZValue(2)
        self.scene.addItem(self.subtitleItem)

        self.playBar = SimpleMediaPlayBar(self)
        self.player = self.playBar.player
        self.videoSurface = _SoftwareVideoSurface(self)
        self.player.setNotifyInterval(100)
        self.player.setVideoOutput(self.videoSurface)
        self.player.setMuted(True)
        self.playBar.volumeButton.setMuted(True)
        self.playBar.progressSlider.setEnabled(False)
        self.playBar.playButton.setEnabled(False)
        self.playBar.volumeButton.setEnabled(False)

        self.timeLabel = CaptionLabel("00:00 / 00:00", self.playBar)
        self.timeLabel.setAlignment(Qt.AlignCenter)
        self.timeLabel.setMinimumWidth(96)
        self.playBar.hBoxLayout.insertWidget(2, self.timeLabel, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.view, 1, Qt.AlignCenter)
        layout.addWidget(self.playBar, 0, Qt.AlignHCenter)

        self.videoSurface.imageAvailable.connect(self._on_video_frame_available)
        self.player.positionChanged.connect(self._update_time_label)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.stateChanged.connect(self._on_player_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._set_canvas_size(self._canvas_size)

    def canvasSize(self) -> Tuple[int, int]:
        return self._canvas_size

    def setSource(
        self,
        video_path: str = "",
        poster_path: str = "",
        canvas_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        video_path = video_path if Path(video_path).is_file() else ""
        poster_path = poster_path if Path(poster_path).is_file() else ""
        forced_canvas = (
            (max(1, int(canvas_size[0])), max(1, int(canvas_size[1])))
            if canvas_size
            else None
        )

        poster_changed = poster_path != self._poster_path
        canvas_changed = forced_canvas != self._forced_canvas
        source_changed = video_path != self._source_path
        self._poster_path = poster_path
        self._forced_canvas = forced_canvas

        if poster_changed:
            self._poster_pixmap = QPixmap(poster_path) if poster_path else QPixmap()

        if source_changed:
            self.player.stop()
            self.videoSurface.resetFrameThrottle()
            self._source_path = video_path
            self._has_started = False
            self._native_size = None
            self._video_pixmap = QPixmap()
            self.videoItem.setPixmap(QPixmap())
            if video_path:
                self.player.setSource(QUrl.fromLocalFile(str(Path(video_path).resolve())))
            else:
                self.player.setMedia(QMediaContent())

        has_video = bool(video_path)
        self.playBar.progressSlider.setEnabled(has_video)
        self.playBar.playButton.setEnabled(has_video)
        self.playBar.volumeButton.setEnabled(has_video)
        self.videoItem.setVisible(has_video)
        self.posterItem.setVisible(not self._has_started or not has_video)

        poster_size = (
            (
                self._poster_pixmap.width(),
                self._poster_pixmap.height(),
            )
            if not self._poster_pixmap.isNull()
            else None
        )
        target_size = select_preview_canvas_size(
            forced_canvas,
            has_video,
            source_changed,
            self._native_size,
            poster_size,
            self._canvas_size,
        )

        if poster_changed or canvas_changed or target_size != self._canvas_size:
            self._set_canvas_size(target_size)

        if source_changed and not has_video:
            self._update_time_label(0)

    def setSubtitleOverlay(self, image_path: str) -> bool:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return False
        width, height = self._canvas_size
        if pixmap.width() != width or pixmap.height() != height:
            pixmap = pixmap.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        self.subtitleItem.setPixmap(pixmap)
        self.subtitleItem.setPos(0, 0)
        return True

    def clearSubtitleOverlay(self) -> None:
        self.subtitleItem.setPixmap(QPixmap())

    def fitView(self) -> None:
        if self.scene.sceneRect().isValid():
            self.view.resetTransform()
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _sync_view_geometry(self) -> None:
        layout = self.layout()
        available_height = max(
            1,
            self.height() - self.playBar.height() - layout.spacing(),
        )
        target_width, target_height = select_preview_view_size(
            self._canvas_size,
            (self.width(), available_height),
        )
        if (
            self.view.width() != target_width
            or self.view.height() != target_height
        ):
            self.view.setFixedSize(target_width, target_height)
        play_bar_width = min(self.width(), 760, max(320, target_width))
        if self.playBar.width() != play_bar_width:
            self.playBar.setFixedWidth(play_bar_width)
        self.fitView()

    def _set_canvas_size(self, size: Tuple[int, int]) -> None:
        width, height = max(1, int(size[0])), max(1, int(size[1]))
        self._canvas_size = (width, height)
        self.scene.setSceneRect(0, 0, width, height)
        self.videoItem.setPos(0, 0)
        self._layout_video_frame()
        self._layout_poster()
        self.fitView()
        QTimer.singleShot(0, self._sync_view_geometry)

    def _layout_video_frame(self) -> None:
        if self._video_pixmap.isNull():
            self.videoItem.setPixmap(QPixmap())
            self.videoItem.setScale(1.0)
            return
        width, height = self._canvas_size
        frame_width = self._video_pixmap.width()
        frame_height = self._video_pixmap.height()
        scale = min(width / frame_width, height / frame_height)
        self.videoItem.setPixmap(self._video_pixmap)
        self.videoItem.setScale(scale)
        self.videoItem.setPos(
            (width - frame_width * scale) / 2,
            (height - frame_height * scale) / 2,
        )

    def _layout_poster(self) -> None:
        if self._poster_pixmap.isNull():
            self.posterItem.setPixmap(QPixmap())
            return
        width, height = self._canvas_size
        pixmap = self._poster_pixmap.scaled(
            width,
            height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.posterItem.setPixmap(pixmap)
        self.posterItem.setPos(
            (width - pixmap.width()) / 2,
            (height - pixmap.height()) / 2,
        )

    def _on_video_frame_available(self, image: QImage) -> None:
        if (
            not self._source_path
            or image.isNull()
            or image.width() <= 0
            or image.height() <= 0
        ):
            return
        native_size = (image.width(), image.height())
        self._native_size = native_size
        self._video_pixmap = QPixmap.fromImage(image)
        if not self._forced_canvas and native_size != self._canvas_size:
            self._set_canvas_size(native_size)
            self.canvasSizeChanged.emit(*native_size)
        else:
            self._layout_video_frame()
        self._has_started = True
        self.posterItem.setVisible(False)

    def _on_duration_changed(self, duration: int) -> None:
        self._update_time_label(self.player.position())

    def _update_time_label(self, position: int) -> None:
        self.timeLabel.setText(
            f"{format_media_time(position)} / {format_media_time(self.player.duration())}"
        )

    def _on_player_state_changed(self, state: QMediaPlayer.State) -> None:
        self.playBar.playButton.setPlay(state == QMediaPlayer.PlayingState)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.InvalidMedia:
            self._has_started = False
            self.posterItem.setVisible(True)
        elif status == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_view_geometry)

    def hideEvent(self, event) -> None:
        self.player.pause()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.player.stop()
        super().closeEvent(event)
