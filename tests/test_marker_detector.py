import unittest

import cv2
import numpy as np

from marker_detector import detect_quadrant_marker, to_display_gray


def make_marker_image(size: tuple[int, int] = (240, 320), center: tuple[int, int] = (157, 111), radius: int = 34) -> np.ndarray:
    image = np.full(size, 120, dtype=np.uint8)
    for start_angle, color in ((0, 245), (90, 15), (180, 245), (270, 15)):
        cv2.ellipse(image, center, (radius, radius), 0, start_angle, start_angle + 90, color, -1)
    cv2.circle(image, center, radius, 128, 1)
    return image


def make_half_marker_image() -> np.ndarray:
    image = np.full((200, 260), 120, dtype=np.uint8)
    cv2.ellipse(image, (130, 100), (30, 30), 0, 0, 180, 245, -1)
    cv2.ellipse(image, (130, 100), (30, 30), 0, 180, 360, 15, -1)
    cv2.circle(image, (130, 100), 30, 128, 1)
    return image


class MarkerDetectorTests(unittest.TestCase):
    def test_detects_alternating_quadrants_and_center(self) -> None:
        detection = detect_quadrant_marker(make_marker_image())

        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertAlmostEqual(detection.center_x, 157, delta=4)
        self.assertAlmostEqual(detection.center_y, 111, delta=4)
        self.assertGreaterEqual(detection.confidence, 0.4)

    def test_rejects_uniform_image(self) -> None:
        image = np.full((120, 160), 100, dtype=np.uint8)

        self.assertIsNone(detect_quadrant_marker(image))

    def test_detects_two_adjacent_bright_and_dark_quarters(self) -> None:
        detection = detect_quadrant_marker(make_half_marker_image())

        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertAlmostEqual(detection.center_x, 130, delta=4)
        self.assertAlmostEqual(detection.center_y, 100, delta=4)

    def test_converts_royale_gray_range(self) -> None:
        image = np.array([[0.0, 300.0, 600.0, 900.0]], dtype=np.float32)

        np.testing.assert_array_equal(to_display_gray(image), [[0, 127, 255, 255]])


if __name__ == "__main__":
    unittest.main()