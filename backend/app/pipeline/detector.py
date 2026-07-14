"""Face detection and embedding models (InsightFace: SCRFD + ArcFace).

Both models come from a single InsightFace model pack (default: buffalo_l),
run on CPU via ONNX Runtime, and are cached under the persistent models
volume so the system is fully offline after first start.

The detector and recognizer are exposed separately so detection can run
every frame while embeddings are computed only for saved captures.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.utils import face_align

from app.logging_setup import get_logger

logger = get_logger("pipeline.detector")

# ONNX Runtime NPU execution providers, in preference order.
# VSINPU = VeriSilicon (Allwinner A733 → Radxa Cubie A7Z, ~3 TOPS);
# RKNPU  = Rockchip (RK3588 family). Present only in vendor/custom ORT builds.
NPU_PROVIDERS: tuple[str, ...] = ("VSINPUExecutionProvider", "RKNPUExecutionProvider")


def resolve_providers(backend: str) -> tuple[list[str], bool]:
    """Map a backend name ("cpu" | "npu") to ONNX Runtime providers.

    Returns (providers, npu_active). "npu" falls back to CPU-only with a
    warning when no NPU execution provider is installed, so the same image
    runs unchanged on hardware without an NPU runtime.
    """
    available = ort.get_available_providers()
    if backend == "npu":
        npu = [p for p in NPU_PROVIDERS if p in available]
        if npu:
            logger.info("NPU execution provider active: %s", npu[0])
            return [*npu, "CPUExecutionProvider"], True
        logger.warning(
            "INFERENCE_BACKEND=npu but no NPU execution provider is installed "
            "(available: %s); falling back to CPU", available,
        )
    return ["CPUExecutionProvider"], False


def npu_runtime_available() -> bool:
    """True when this onnxruntime build ships an NPU execution provider."""
    return any(p in ort.get_available_providers() for p in NPU_PROVIDERS)


@dataclass
class Detection:
    """One detected face in frame coordinates."""

    bbox: tuple[int, int, int, int]  # x, y, w, h
    score: float
    kps: np.ndarray  # 5x2 facial landmarks


class FaceModels:
    """Owns the SCRFD detector and ArcFace recognizer."""

    def __init__(
        self,
        model_pack: str,
        models_dir: Path,
        detection_size: int,
        detection_confidence: float,
        min_face_size: int,
        providers: list[str] | None = None,
    ) -> None:
        self._detection_confidence = detection_confidence
        self._min_face_size = min_face_size
        self.model_pack = model_pack
        providers = providers or ["CPUExecutionProvider"]

        logger.info("Loading InsightFace model pack '%s' (providers=%s)",
                    model_pack, providers)
        self._analysis = FaceAnalysis(
            name=model_pack,
            root=str(models_dir),
            allowed_modules=["detection", "recognition"],
            providers=providers,
        )
        self._analysis.prepare(
            ctx_id=-1,
            det_size=(detection_size, detection_size),
            det_thresh=detection_confidence,
        )
        self._detector = self._analysis.models["detection"]
        self._recognizer = self._analysis.models["recognition"]
        logger.info("Face models ready (det_size=%d, conf=%.2f)",
                    detection_size, detection_confidence)

    # -- Detection ---------------------------------------------------------

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Detect faces; returns boxes above the confidence and size floors."""
        bboxes, kpss = self._detector.detect(frame_bgr, max_num=0, metric="default")
        detections: list[Detection] = []
        if bboxes is None or len(bboxes) == 0:
            return detections

        height, width = frame_bgr.shape[:2]
        for i, row in enumerate(bboxes):
            x1, y1, x2, y2, score = row
            if score < self._detection_confidence:
                continue
            x1 = max(0, int(x1))
            y1 = max(0, int(y1))
            x2 = min(width, int(x2))
            y2 = min(height, int(y2))
            w, h = x2 - x1, y2 - y1
            if min(w, h) < self._min_face_size:
                continue
            kps = kpss[i] if kpss is not None else np.zeros((5, 2), dtype=np.float32)
            detections.append(Detection(bbox=(x1, y1, w, h), score=float(score), kps=kps))
        return detections

    # -- Embeddings ----------------------------------------------------------

    @staticmethod
    def align(frame_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """Warp the face at `kps` to the canonical 112x112 ArcFace crop.

        Cheap (a single warpAffine), so it runs in the detection worker;
        only the small aligned crop travels through queues, never full frames.
        """
        return face_align.norm_crop(frame_bgr, landmark=kps, image_size=112)

    def embed_aligned(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """Return an L2-normalized 512-d embedding for an aligned 112x112 crop."""
        embedding = self._recognizer.get_feat(aligned_bgr).flatten().astype(np.float32)
        norm = float(np.linalg.norm(embedding))
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def embed(self, frame_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """Detect-free convenience: align then embed (used by the search API)."""
        return self.embed_aligned(self.align(frame_bgr, kps))

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the recognition embedding (512 for buffalo_l)."""
        return 512

    @property
    def active_providers(self) -> list[str]:
        """Execution providers actually bound to the ONNX sessions."""
        session = getattr(self._recognizer, "session", None)
        if session is not None:
            return list(session.get_providers())
        return []
