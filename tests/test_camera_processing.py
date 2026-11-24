import argparse
import os
import queue
import unittest
from unittest.mock import patch

import numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from roypypack import roypy

from app import CameraView, _position_at_marker, open_camera
from marker_detector import MarkerDetection


class FakeBridge:
    def __init__(self) -> None:
        self.messages = []
        self.arrow = {"dx": 1.0, "dy": 0.0, "length": 1.0}

    def publish(self, message) -> None:
        self.messages.append(message)

    def take_latest_arrow(self):
        arrow, self.arrow = self.arrow, None
        return arrow

    def stop(self) -> None:
        pass


class CameraProcessingTests(unittest.TestCase):
    def test_camera_discovery_returns_offline_mode_when_no_device_is_connected(self) -> None:
        class EmptyCameraList:
            def size(self) -> int:
                return 0

        class EmptyCameraManager:
            def getConnectedCameraList(self):
                return EmptyCameraList()

        with patch.object(roypy, "CameraManager", return_value=EmptyCameraManager()):
            self.assertIsNone(open_camera())

    def test_position_uses_valid_point_cloud_samples_near_marker_center(self) -> None:
        points = np.zeros((24, 24, 5), dtype=np.float32)
        points[:, :, 0] = 0.12
        points[:, :, 1] = -0.08
        points[:, :, 2] = 1.4
        points[:, :, 4] = 1.0
        points[11, 11, 2] = 2.0
        points[11, 11, 4] = 0.0
        detection = MarkerDetection(center_x=12, center_y=12, radius=6, confidence=0.9)

        position = _position_at_marker(points, detection)

        self.assertIsNotNone(position)
        assert position is not None
        np.testing.assert_allclose(position, (0.12, -0.08, 1.4), rtol=1e-6)

    def test_offline_view_stays_black_and_publishes_zero_detection_with_arrow(self) -> None:
        qt_app = QApplication.instance() or QApplication([])
        bridge = FakeBridge()
        args = argparse.Namespace(marker_min_radius=6, marker_max_radius=0, marker_min_confidence=0.4)
        view = CameraView(bridge, None, queue.Queue(), args, camera_available=False)
        view.resize(640, 480)
        view.timer.stop()

        view._update_from_camera()

        self.assertEqual(view.image.pixelColor(20, 20).value(), 0)
        self.assertEqual(bridge.messages[-1]["position_m"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(bridge.messages[-1]["confidence"], 0.0)
        self.assertFalse(bridge.messages[-1]["detected"])
        self.assertEqual(view.arrow["length"], 1.0)

        surface = QImage(640, 480, QImage.Format.Format_RGB32)
        view.render(surface)
        self.assertGreater(surface.pixelColor(360, 240).green(), 180)
        view.close()
        self.assertIsNotNone(qt_app)


if __name__ == "__main__":
    unittest.main()