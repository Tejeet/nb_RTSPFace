"""Per-camera front-of-pipeline bundle.

Everything unique to one camera — the RTSP reader, its frame queue, detector
worker, tracker, capture zone and live-view buffer. Multiple instances run in
parallel and all feed the single shared embedding/storage back-end, so adding
a camera is just adding one more of these.
"""

import queue

from app.config import Settings
from app.pipeline.camera import CameraReader, FramePacket
from app.pipeline.cropper import FaceCropper
from app.pipeline.detector import FaceModels
from app.pipeline.live import LiveFrameBuffer
from app.pipeline.quality import QualityEvaluator
from app.pipeline.stats import StatsCollector
from app.pipeline.tracker import ByteTracker
from app.pipeline.workers import CaptureJob, DetectionWorker
from app.pipeline.zone import CaptureZone


class CameraPipeline:
    """Reader + detection worker + tracker + live buffer for a single camera."""

    def __init__(
        self,
        camera_id: int,
        camera_name: str,
        rtsp_url: str,
        settings: Settings,
        models: FaceModels,
        cropper: FaceCropper,
        quality: QualityEvaluator,
        embed_queue: "queue.Queue[CaptureJob | None]",
        zone: CaptureZone,
    ) -> None:
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.stats = StatsCollector()

        self._frame_queue: queue.Queue[FramePacket] = queue.Queue(settings.frame_queue_size)
        self.live_buffer = LiveFrameBuffer(
            target_width=settings.live_stream_width,
            max_fps=settings.live_stream_fps,
            zone=zone,
        )
        self.tracker = ByteTracker(
            match_iou=settings.track_match_iou,
            min_hits=settings.track_min_hits,
            max_lost_frames=settings.track_max_lost_frames,
            low_score_threshold=settings.track_low_score_threshold,
            high_score_threshold=settings.detection_confidence,
        )
        self.camera = CameraReader(
            rtsp_url=rtsp_url,
            frame_queue=self._frame_queue,
            reconnect_min_delay=settings.camera_reconnect_min_delay,
            reconnect_max_delay=settings.camera_reconnect_max_delay,
            rtsp_transport=settings.rtsp_transport,
        )
        self.detection_worker = DetectionWorker(
            settings=settings,
            frame_queue=self._frame_queue,
            embed_queue=embed_queue,
            models=models,
            tracker=self.tracker,
            quality=quality,
            cropper=cropper,
            live_buffer=self.live_buffer,
            stats=self.stats,
            camera_fps=lambda: self.camera.state.fps,
            zone=zone,
            camera_id=camera_id,
            camera_name=camera_name,
        )

    def start(self) -> None:
        self.camera.start()
        self.detection_worker.start()

    def stop(self) -> None:
        self.camera.stop()
        self.detection_worker.stop()

    def join(self, timeout: float) -> None:
        self.detection_worker.join(timeout=timeout)
        self.camera.join(timeout=timeout)

    def live_status(self) -> dict[str, object]:
        """Realtime status for this camera."""
        camera = self.camera.state.snapshot()
        pipeline = self.stats.snapshot()
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "camera_connected": camera["connected"],
            "fps": camera["fps"],
            "faces_in_frame": pipeline["faces_in_frame"],
            "visible_faces": pipeline["visible_faces"],
            "tracked_faces": pipeline["tracked_faces"],
            "frame_width": camera["frame_width"],
            "frame_height": camera["frame_height"],
        }
