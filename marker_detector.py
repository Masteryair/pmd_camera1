from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class MarkerDetection:
    center_x: float
    center_y: float
    radius: float
    confidence: float


def to_display_gray(gray: np.ndarray) -> np.ndarray:
    """Convert Royale's gray channel to an 8-bit image using its documented sample range."""
    values = np.asarray(gray)
    if values.ndim != 2:
        raise ValueError("Expected a two-dimensional gray image")
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.ascontiguousarray(np.clip(values, 0, 600) * (255.0 / 600.0), dtype=np.uint8)


def detect_quadrant_marker(
    gray: np.ndarray,
    min_radius: int = 6,
    max_radius: int | None = None,
    min_confidence: float = 0.4,
) -> MarkerDetection | None:
    """Find a circular marker with two bright and two dark 90-degree sectors."""
    image = np.asarray(gray)
    if image.ndim != 2:
        raise ValueError("Expected a two-dimensional gray image")
    if image.dtype != np.uint8:
        image = np.nan_to_num(image, nan=0.0, posinf=0.0, neginf=0.0)
        image = np.clip(image, 0, 255).astype(np.uint8)
    if min(image.shape) < 2 * min_radius + 1 or int(image.max()) == int(image.min()):
        return None

    height, width = image.shape
    if max_radius is None:
        max_radius = max(min_radius, min(height, width) // 3)

    blurred = cv2.GaussianBlur(image, (5, 5), 1.2)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(10, min(height, width) * 0.08),
        param1=80,
        param2=18,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return None

    best: MarkerDetection | None = None
    for circle_x, circle_y, radius in circles[0]:
        confidence = _pattern_confidence(image, float(circle_x), float(circle_y), float(radius))
        if confidence >= min_confidence and (best is None or confidence > best.confidence):
            best = MarkerDetection(float(circle_x), float(circle_y), float(radius), confidence)
    return best


def _pattern_confidence(image: np.ndarray, center_x: float, center_y: float, radius: float) -> float:
    angles = np.linspace(0.0, 2.0 * np.pi, 180, endpoint=False)
    radial_fractions = np.array([0.38, 0.5, 0.62, 0.74])
    sample_radii = radius * radial_fractions
    x_coords = center_x + np.cos(angles)[None, :] * sample_radii[:, None]
    y_coords = center_y + np.sin(angles)[None, :] * sample_radii[:, None]
    x_indices = np.clip(np.rint(x_coords).astype(int), 0, image.shape[1] - 1)
    y_indices = np.clip(np.rint(y_coords).astype(int), 0, image.shape[0] - 1)
    angular_values = image[y_indices, x_indices].astype(np.float32).mean(axis=0)

    centered = angular_values - float(angular_values.mean())
    magnitude = float(np.linalg.norm(centered))
    if magnitude < 1.0:
        return 0.0

    best_correlation = 0.0
    rotations = np.linspace(0.0, np.pi / 2.0, 46, endpoint=False)
    sector_ids = np.floor(
        ((angles[None, :] - rotations[:, None]) % (2.0 * np.pi)) / (np.pi / 2.0)
    ).astype(int)
    patterns = ((1, 1, -1, -1), (1, -1, 1, -1))
    for pattern in patterns:
        for sequence in _rotations(pattern):
            expected = np.asarray(sequence, dtype=np.float32)[sector_ids]
            expected -= expected.mean(axis=1, keepdims=True)
            denominator = magnitude * np.linalg.norm(expected, axis=1)
            correlations = np.abs(expected @ centered) / np.maximum(denominator, 1.0)
            best_correlation = max(best_correlation, float(correlations.max()))

    contrast = float(np.percentile(angular_values, 90) - np.percentile(angular_values, 10))
    contrast_factor = min(1.0, contrast / 80.0)
    return float(np.clip(best_correlation * contrast_factor, 0.0, 1.0))


def _rotations(pattern: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    return tuple(dict.fromkeys(pattern[index:] + pattern[:index] for index in range(len(pattern))))