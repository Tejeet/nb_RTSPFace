"""SCRFD post-processing (pure NumPy).

A Hailo HEF emits SCRFD's raw per-stride tensors; this module turns them
into face boxes, scores and landmarks. Kept free of any Hailo or ONNX
import so the decoding maths can be unit-tested on any machine.

SCRFD layout: three strides (8, 16, 32), two anchors per feature-map cell,
and three tensors per stride — class score, bbox distances, and 5 keypoint
offsets, all expressed in stride units from the anchor centre.
"""

from dataclasses import dataclass

import numpy as np

STRIDES: tuple[int, ...] = (8, 16, 32)
NUM_ANCHORS = 2
NUM_KEYPOINTS = 5


@dataclass
class DecodedFaces:
    """Decoded detections in network-input coordinates."""

    boxes: np.ndarray  # (N, 4) x1, y1, x2, y2
    scores: np.ndarray  # (N,)
    keypoints: np.ndarray  # (N, 5, 2)


def anchor_centers(height: int, width: int, stride: int, num_anchors: int) -> np.ndarray:
    """Anchor centre coordinates (x, y) in pixels, one row per anchor."""
    grid = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
    centers = (grid * stride).reshape(-1, 2)
    if num_anchors > 1:
        # Anchors at the same cell must be adjacent rows, matching the way the
        # network interleaves its per-anchor channels.
        centers = np.repeat(centers, num_anchors, axis=0)
    return centers


def distance2bbox(centers: np.ndarray, distances: np.ndarray) -> np.ndarray:
    """Convert (left, top, right, bottom) distances into absolute boxes."""
    x1 = centers[:, 0] - distances[:, 0]
    y1 = centers[:, 1] - distances[:, 1]
    x2 = centers[:, 0] + distances[:, 2]
    y2 = centers[:, 1] + distances[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(centers: np.ndarray, distances: np.ndarray) -> np.ndarray:
    """Convert per-keypoint (dx, dy) offsets into absolute (x, y) points."""
    points = []
    for i in range(0, distances.shape[1], 2):
        points.append(centers[:, 0] + distances[:, i])
        points.append(centers[:, 1] + distances[:, i + 1])
    return np.stack(points, axis=-1)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression; returns kept indices, best score first."""
    if boxes.shape[0] == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        best = order[0]
        keep.append(int(best))
        if order.size == 1:
            break
        rest = order[1:]
        ix1 = np.maximum(x1[best], x1[rest])
        iy1 = np.maximum(y1[best], y1[rest])
        ix2 = np.minimum(x2[best], x2[rest])
        iy2 = np.minimum(y2[best], y2[rest])
        inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
        union = areas[best] + areas[rest] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[iou <= iou_threshold]
    return keep


def group_outputs_by_stride(
    outputs: dict[str, np.ndarray], input_size: int
) -> dict[int, dict[str, np.ndarray]]:
    """Sort raw network outputs into {stride: {"score"|"bbox"|"kps": tensor}}.

    Tensors are identified by shape rather than by name, because HEF output
    names vary between Hailo Model Zoo builds. Within a stride the channel
    count is unambiguous: 2 anchors → 2 score, 8 bbox, 20 keypoint channels.
    """
    grouped: dict[int, dict[str, np.ndarray]] = {}
    channel_roles = {
        NUM_ANCHORS: "score",
        NUM_ANCHORS * 4: "bbox",
        NUM_ANCHORS * NUM_KEYPOINTS * 2: "kps",
    }

    for tensor in outputs.values():
        array = np.asarray(tensor)
        if array.ndim == 4:  # (batch, H, W, C)
            array = array[0]
        if array.ndim != 3:
            raise ValueError(
                f"Unexpected SCRFD output rank {array.ndim}; expected NHWC or HWC"
            )
        height, _width, channels = array.shape
        role = channel_roles.get(channels)
        if role is None:
            continue  # not an SCRFD head we recognise
        stride = input_size // height
        if stride not in STRIDES:
            continue
        grouped.setdefault(stride, {})[role] = array
    return grouped


class UnsupportedOutputLayout(ValueError):
    """Raised when the network's outputs are not raw SCRFD heads.

    Most often this means the HEF was compiled with NMS post-processing
    built in, which emits decoded detections in a different format —
    a different HEF (or decoder) is needed.
    """


def decode(
    outputs: dict[str, np.ndarray],
    input_size: int,
    score_threshold: float,
    iou_threshold: float = 0.4,
) -> DecodedFaces:
    """Decode raw SCRFD outputs into NMS-filtered detections.

    Raises UnsupportedOutputLayout if no recognisable SCRFD head is found,
    so a mismatched model surfaces immediately instead of looking like a
    camera that simply never sees anyone.
    """
    grouped = group_outputs_by_stride(outputs, input_size)
    if not grouped:
        shapes = {name: np.asarray(t).shape for name, t in outputs.items()}
        raise UnsupportedOutputLayout(
            "No raw SCRFD heads found in the model output. Expected per-stride "
            f"tensors with 2/8/20 channels; got {shapes}. If this HEF was compiled "
            "with built-in NMS, use a raw-output SCRFD build instead."
        )

    all_boxes: list[np.ndarray] = []
    all_scores: list[np.ndarray] = []
    all_kps: list[np.ndarray] = []

    for stride in STRIDES:
        heads = grouped.get(stride)
        if not heads or not {"score", "bbox"} <= heads.keys():
            continue

        height, width = heads["score"].shape[:2]
        centers = anchor_centers(height, width, stride, NUM_ANCHORS)

        scores = heads["score"].reshape(-1)
        keep = scores >= score_threshold
        if not keep.any():
            continue

        # Distances are predicted in stride units.
        bbox_distances = heads["bbox"].reshape(-1, 4) * stride
        boxes = distance2bbox(centers, bbox_distances)[keep]

        if "kps" in heads:
            kps_distances = heads["kps"].reshape(-1, NUM_KEYPOINTS * 2) * stride
            keypoints = distance2kps(centers, kps_distances)[keep]
        else:
            keypoints = np.zeros((int(keep.sum()), NUM_KEYPOINTS * 2), dtype=np.float32)

        all_boxes.append(boxes)
        all_scores.append(scores[keep])
        all_kps.append(keypoints.reshape(-1, NUM_KEYPOINTS, 2))

    if not all_boxes:
        return DecodedFaces(
            boxes=np.zeros((0, 4), np.float32),
            scores=np.zeros((0,), np.float32),
            keypoints=np.zeros((0, NUM_KEYPOINTS, 2), np.float32),
        )

    boxes = np.concatenate(all_boxes).astype(np.float32)
    scores = np.concatenate(all_scores).astype(np.float32)
    keypoints = np.concatenate(all_kps).astype(np.float32)

    kept = nms(boxes, scores, iou_threshold)
    return DecodedFaces(boxes=boxes[kept], scores=scores[kept], keypoints=keypoints[kept])


def letterbox(image_bgr: np.ndarray, input_size: int) -> tuple[np.ndarray, float]:
    """Resize keeping aspect ratio, pad to a square canvas; returns (canvas, scale).

    Padding is added at the right/bottom only, so undoing it is a single
    division by `scale` — no offset bookkeeping.
    """
    import cv2

    height, width = image_bgr.shape[:2]
    scale = min(input_size / width, input_size / height)
    new_width = int(round(width * scale))
    new_height = int(round(height * scale))
    resized = cv2.resize(image_bgr, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((input_size, input_size, 3), dtype=image_bgr.dtype)
    canvas[:new_height, :new_width] = resized
    return canvas, scale
