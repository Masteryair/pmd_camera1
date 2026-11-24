from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from marker_detector import MarkerDetection, detect_quadrant_marker, to_display_gray
from websocket_bridge import WebSocketBridge


logger = logging.getLogger("pmd_camera")
_SDK_DLL_DIRECTORY = None


@dataclass(frozen=True)
class DetectionResult:
    detection: MarkerDetection | None
    position: tuple[float, float, float] | None


class CameraFrameListener:
    def __init__(self) -> None:
        from roypypack import roypy

        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
        self.listener = _create_listener(roypy, self.queue)


def _create_listener(roypy: Any, frames: queue.Queue[np.ndarray]) -> Any:
    class Listener(roypy.IDepthDataListener):
        def __init__(self) -> None:
            super().__init__()

        def onNewData(self, data: Any) -> None:
            try:
                points = np.asarray(data.npoints(), dtype=np.float32).copy()
                if points.ndim != 3 or points.shape[2] < 5:
                    logger.error("Unexpected Royale point-cloud shape: %s", points.shape)
                    return
                try:
                    frames.put_nowait(points)
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    frames.put_nowait(points)
            except Exception:
                logger.exception("Could not copy a camera frame")

    return Listener()


def open_camera() -> tuple[Any, Any, CameraFrameListener] | None:
    from roypypack import roypy

    manager = roypy.CameraManager()
    cameras = manager.getConnectedCameraList()
    if cameras.size() == 0:
        logger.warning("No PMD camera was found; starting in camera-offline mode")
        return None

    camera = manager.createCamera(cameras[0])
    camera.initialize()
    frame_listener = CameraFrameListener()
    camera.registerDataListener(frame_listener.listener)
    camera.startCapture()
    logger.info("Camera capture started; supported modes: %s", list(camera.getUseCases()))
    return manager, camera, frame_listener


class CameraView(QWidget):
    def __init__(
        self,
        bridge: WebSocketBridge,
        camera: Any | None,
        frames: queue.Queue[np.ndarray],
        args: argparse.Namespace,
        camera_available: bool,
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.camera = camera
        self.camera_available = camera_available
        self.frames = frames
        self.args = args
        self.image: QImage | None = QImage(640, 480, QImage.Format.Format_Grayscale8)
        self.image.fill(0)
        self.frame_shape: tuple[int, int] | None = (480, 640)
        self.result = DetectionResult(None, (0.0, 0.0, 0.0))
        self.arrow = {"dx": 0.0, "dy": 0.0, "length": 0.0}
        self.frame_number = 0
        self._last_offline_publish = 0.0
        self.setWindowTitle("PMD Flexx2 Camera")
        self.setMinimumSize(640, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_from_camera)
        self.timer.start(33 if camera_available else 100)

    def _update_from_camera(self) -> None:
        latest = None
        while True:
            try:
                latest = self.frames.get_nowait()
            except queue.Empty:
                break
        self.arrow = self.bridge.take_latest_arrow() or self.arrow
        if latest is None:
            if not self.camera_available:
                self.result = DetectionResult(None, (0.0, 0.0, 0.0))
                now = time.monotonic()
                if now - self._last_offline_publish >= 0.1:
                    self.bridge.publish(self._detection_message())
                    self._last_offline_publish = now
                self.update()
            return

        self.frame_number += 1
        gray = latest[:, :, 3]
        valid = (latest[:, :, 4] > 0) & np.isfinite(gray)
        display = to_display_gray(gray)
        display[~valid] = 0
        self.frame_shape = display.shape
        self.image = QImage(
            display.data,
            display.shape[1],
            display.shape[0],
            display.strides[0],
            QImage.Format.Format_Grayscale8,
        ).copy()

        detection = detect_quadrant_marker(
            display,
            min_radius=self.args.marker_min_radius,
            max_radius=self.args.marker_max_radius or None,
            min_confidence=self.args.marker_min_confidence,
        )
        position = _position_at_marker(latest, detection) if detection is not None else (0.0, 0.0, 0.0)
        self.result = DetectionResult(detection, position)
        self.bridge.publish(self._detection_message())
        self.update()

    def _detection_message(self) -> dict[str, Any]:
        detection = self.result.detection
        position = self.result.position
        if detection is None and position is None:
            position = (0.0, 0.0, 0.0)
        return {
            "type": "detection",
            "timestamp": time.time(),
            "frame": self.frame_number,
            "detected": detection is not None,
            "position_m": None if position is None else {"x": position[0], "y": position[1], "z": position[2]},
            "center_px": None if detection is None else {"x": detection.center_x, "y": detection.center_y},
            "confidence": 0.0 if detection is None else detection.confidence,
        }

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 11, 14))
        image_rect = self._image_rect()
        if self.image is not None and image_rect is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(image_rect, self.image)
            self._draw_detection(painter, image_rect)
            self._draw_arrow(painter, image_rect)
        self._draw_status(painter)

    def _image_rect(self) -> QRectF | None:
        if self.image is None or self.image.isNull():
            return None
        image_width = self.image.width()
        image_height = self.image.height()
        scale = min(self.width() / image_width, self.height() / image_height)
        width = image_width * scale
        height = image_height * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _draw_detection(self, painter: QPainter, image_rect: QRectF) -> None:
        detection = self.result.detection
        if detection is None or self.frame_shape is None:
            return
        height, width = self.frame_shape
        x = image_rect.left() + detection.center_x * image_rect.width() / width
        y = image_rect.top() + detection.center_y * image_rect.height() / height
        radius = detection.radius * image_rect.width() / width
        painter.setPen(QPen(QColor(255, 215, 72), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(x - radius, y - radius, 2 * radius, 2 * radius))
        painter.drawLine(QLineF(x - 8, y, x + 8, y))
        painter.drawLine(QLineF(x, y - 8, x, y + 8))

    def _draw_arrow(self, painter: QPainter, image_rect: QRectF) -> None:
        dx = self.arrow["dx"]
        dy = self.arrow["dy"]
        length_fraction = self.arrow["length"]
        if length_fraction <= 0 or (dx == 0 and dy == 0):
            return
        start = image_rect.center()
        maximum_length = image_rect.height() / 4.0
        end_x = start.x() + dx * maximum_length * length_fraction
        end_y = start.y() + dy * maximum_length * length_fraction
        painter.setPen(QPen(QColor(45, 230, 190), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QLineF(start.x(), start.y(), end_x, end_y))

        angle = np.arctan2(dy, dx)
        head_length = 16.0
        points = QPolygonF(
            [
                QPointF(end_x, end_y),
                QPointF(end_x - head_length * np.cos(angle - 0.5), end_y - head_length * np.sin(angle - 0.5)),
                QPointF(end_x - head_length * np.cos(angle + 0.5), end_y - head_length * np.sin(angle + 0.5)),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(45, 230, 190))
        painter.drawPolygon(points)

    def _draw_status(self, painter: QPainter) -> None:
        panel = QRectF(max(16, self.width() - 330), 18, 312, 156)
        painter.setPen(QPen(QColor(87, 105, 117), 1))
        painter.setBrush(QColor(14, 20, 25, 232))
        painter.drawRoundedRect(panel, 5, 5)

        painter.setPen(QColor(239, 244, 246))
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        painter.drawText(panel.adjusted(16, 12, -12, -118), Qt.AlignmentFlag.AlignLeft, "PMD FLEXX2")

        detection = self.result.detection
        painter.setFont(QFont("Segoe UI", 11))
        if not self.camera_available:
            painter.setPen(QColor(246, 184, 74))
            painter.drawText(panel.adjusted(16, 48, -12, -86), Qt.AlignmentFlag.AlignLeft, "CAMERA OFFLINE")
            coordinates = "X  +0.000 m   Y  +0.000 m   Z  +0.000 m"
            score = "Detection score  0%"
        elif detection is None:
            painter.setPen(QColor(183, 197, 205))
            painter.drawText(panel.adjusted(16, 48, -12, -86), Qt.AlignmentFlag.AlignLeft, "Marker not detected")
            coordinates = "X  +0.000 m   Y  +0.000 m   Z  +0.000 m"
            score = "Detection score  0%"
        else:
            painter.setPen(QColor(45, 230, 190))
            painter.drawText(panel.adjusted(16, 48, -12, -86), Qt.AlignmentFlag.AlignLeft, "MARKER DETECTED")
            if self.result.position is None:
                coordinates = "X  --      Y  --      Z  --"
            else:
                x, y, z = self.result.position
                coordinates = f"X  {x:+.3f} m   Y  {y:+.3f} m   Z  {z:.3f} m"
            score = f"Detection score  {detection.confidence * 100:.0f}%"
        painter.setPen(QColor(229, 235, 238))
        painter.drawText(panel.adjusted(16, 82, -12, -54), Qt.AlignmentFlag.AlignLeft, coordinates)
        painter.setPen(QColor(183, 197, 205))
        painter.drawText(panel.adjusted(16, 112, -12, -18), Qt.AlignmentFlag.AlignLeft, score)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: Any) -> None:
        self.timer.stop()
        try:
            if self.camera is not None:
                self.camera.stopCapture()
        except Exception:
            logger.exception("Error while stopping camera capture")
        self.bridge.stop()
        event.accept()


def _position_at_marker(points: np.ndarray, detection: MarkerDetection) -> tuple[float, float, float] | None:
    height, width = points.shape[:2]
    radius = max(2.0, detection.radius * 0.35)
    left = max(0, int(detection.center_x - radius))
    right = min(width, int(detection.center_x + radius + 1))
    top = max(0, int(detection.center_y - radius))
    bottom = min(height, int(detection.center_y + radius + 1))
    region = points[top:bottom, left:right]
    if region.size == 0:
        return None

    y_coords, x_coords = np.ogrid[top:bottom, left:right]
    inside = (x_coords - detection.center_x) ** 2 + (y_coords - detection.center_y) ** 2 <= radius**2
    xyz = region[:, :, :3]
    valid = inside & (region[:, :, 4] > 0) & np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > 0)
    values = xyz[valid]
    if values.shape[0] == 0:
        return None
    position = np.median(values, axis=0)
    return float(position[0]), float(position[1]), float(position[2])


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fullscreen PMD Flexx2 marker monitor")
    parser.add_argument("--ws-host", default="127.0.0.1", help="WebSocket bind address; use 0.0.0.0 for LAN access")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket server port")
    parser.add_argument("--marker-min-radius", type=int, default=6, help="Smallest marker radius in camera pixels")
    parser.add_argument("--marker-max-radius", type=int, default=0, help="Largest marker radius; 0 selects an automatic limit")
    parser.add_argument("--marker-min-confidence", type=float, default=0.4, help="Detection threshold from 0 to 1")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _arguments()
    if not 0 <= args.marker_min_confidence <= 1:
        raise SystemExit("--marker-min-confidence must be between 0 and 1")

    global _SDK_DLL_DIRECTORY
    sdk_bin = os.path.join(os.path.dirname(__file__), "5.16.1.3725", "bin")
    if os.path.isdir(sdk_bin):
        _SDK_DLL_DIRECTORY = os.add_dll_directory(sdk_bin)

    app = QApplication(sys.argv)
    bridge = WebSocketBridge(args.ws_host, args.ws_port)
    try:
        bridge.start()
        camera_setup = open_camera()
    except Exception as error:
        bridge.stop()
        QMessageBox.critical(None, "PMD camera startup failed", str(error))
        return 1

    if camera_setup is None:
        camera = None
        frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
        camera_available = False
    else:
        camera_manager, camera, listener = camera_setup
        frames = listener.queue
        camera_available = True

    view = CameraView(bridge, camera, frames, args, camera_available)
    if camera_setup is not None:
        view.camera_manager = camera_manager
    view.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())