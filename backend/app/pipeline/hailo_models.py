"""Hailo-8 backed face detection (and optionally recognition).

Implements the same surface as `FaceModels` — detect / align /
embed_aligned / embed / embedding_dim — so the pipeline is unaware of
which accelerator is in use.

Split of work by default:
  * SCRFD detection  → Hailo-8   (runs every frame; ~80% of the CPU cost)
  * ArcFace embedding → CPU ONNX (runs only for saved captures)

Recognition can also be moved to the Hailo by supplying a recognition
HEF, but the two networks then contend for the accelerator, so it is
off unless explicitly configured.
"""

from pathlib import Path

import cv2
import numpy as np
from insightface.utils import face_align

from app.logging_setup import get_logger
from app.pipeline import scrfd_decode
from app.pipeline.detector import Detection
from app.pipeline.hailo_runtime import HailoNetwork

logger = get_logger("pipeline.hailo_models")

ARCFACE_INPUT = 112


class HailoFaceModels:
    """Face detection on the Hailo-8, with CPU or Hailo recognition."""

    def __init__(
        self,
        detection_hef: Path,
        detection_confidence: float,
        min_face_size: int,
        models_dir: Path,
        model_pack: str,
        recognition_hef: Path | None = None,
        nms_iou: float = 0.4,
    ) -> None:
        self._detection_confidence = detection_confidence
        self._min_face_size = min_face_size
        self._nms_iou = nms_iou
        self.model_pack = model_pack

        self._detector = HailoNetwork(detection_hef)
        self._input_size = self._detector.input_size

        self._recognizer_hailo: HailoNetwork | None = None
        self._recognizer_cpu = None
        self._layout_verified = False

        if recognition_hef is not None:
            self._recognizer_hailo = HailoNetwork(recognition_hef)
            logger.info("Recognition running on Hailo: %s", recognition_hef.name)
        else:
            self._recognizer_cpu = self._load_cpu_recognizer(models_dir, model_pack)
            logger.info("Recognition running on CPU (ArcFace ONNX)")

    @staticmethod
    def _load_cpu_recognizer(models_dir: Path, model_pack: str):
        """Load only the ArcFace recogniser from the InsightFace pack."""
        from insightface.app import FaceAnalysis

        analysis = FaceAnalysis(
            name=model_pack,
            root=str(models_dir),
            allowed_modules=["recognition"],
            providers=["CPUExecutionProvider"],
        )
        analysis.prepare(ctx_id=-1)
        return analysis.models["recognition"]

    # -- Detection ---------------------------------------------------------

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Detect faces on the accelerator; returns frame-coordinate boxes."""
        canvas, scale = scrfd_decode.letterbox(frame_bgr, self._input_size)
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)

        outputs = self._detector.infer(rgb)
        try:
            decoded = scrfd_decode.decode(
                outputs,
                input_size=self._input_size,
                score_threshold=self._detection_confidence,
                iou_threshold=self._nms_iou,
            )
        except scrfd_decode.UnsupportedOutputLayout:
            # Log the mismatch once, loudly, rather than on every frame.
            if not self._layout_verified:
                self._layout_verified = True
                logger.exception("Hailo detection HEF has an incompatible output layout")
            raise

        if not self._layout_verified:
            self._layout_verified = True
            logger.info("Hailo SCRFD output layout verified (%d heads)", len(outputs))

        frame_h, frame_w = frame_bgr.shape[:2]
        detections: list[Detection] = []
        for box, score, kps in zip(
            decoded.boxes, decoded.scores, decoded.keypoints, strict=True
        ):
            # Undo the letterbox: padding was bottom/right only, so a single
            # divide returns original-frame coordinates.
            x1 = max(0, int(box[0] / scale))
            y1 = max(0, int(box[1] / scale))
            x2 = min(frame_w, int(box[2] / scale))
            y2 = min(frame_h, int(box[3] / scale))
            width, height = x2 - x1, y2 - y1
            if min(width, height) < self._min_face_size:
                continue
            detections.append(
                Detection(
                    bbox=(x1, y1, width, height),
                    score=float(score),
                    kps=(kps / scale).astype(np.float32),
                )
            )
        return detections

    # -- Embeddings ----------------------------------------------------------

    @staticmethod
    def align(frame_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """Warp the face at `kps` to the canonical 112x112 ArcFace crop."""
        return face_align.norm_crop(frame_bgr, landmark=kps, image_size=ARCFACE_INPUT)

    def embed_aligned(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """Return an L2-normalized 512-d embedding for an aligned crop."""
        if self._recognizer_hailo is not None:
            rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)
            outputs = self._recognizer_hailo.infer(rgb)
            embedding = next(iter(outputs.values())).flatten().astype(np.float32)
        else:
            embedding = (
                self._recognizer_cpu.get_feat(aligned_bgr).flatten().astype(np.float32)
            )
        norm = float(np.linalg.norm(embedding))
        return embedding / norm if norm > 0 else embedding

    def embed(self, frame_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """Align then embed (used by the search API)."""
        return self.embed_aligned(self.align(frame_bgr, kps))

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the recognition embedding."""
        return 512

    @property
    def active_providers(self) -> list[str]:
        """Human-readable backend description for the Settings page."""
        recognition = "Hailo-8" if self._recognizer_hailo is not None else "CPU"
        return ["HailoRT detection (Hailo-8)", f"{recognition} recognition"]

    def close(self) -> None:
        """Release accelerator resources."""
        self._detector.close()
        if self._recognizer_hailo is not None:
            self._recognizer_hailo.close()
