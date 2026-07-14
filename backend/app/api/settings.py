"""Runtime settings endpoints (inference backend / hardware acceleration).

The choice is persisted in the data volume and applied when the backend
container restarts — swapping ONNX sessions mid-pipeline is not worth the
risk on an edge device, and a restart takes seconds.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import InferenceInfo, InferenceUpdate

logger = get_logger("api.settings")

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings/inference", response_model=InferenceInfo)
def get_inference_settings(pipeline: Pipeline = Depends(get_pipeline)) -> InferenceInfo:
    """Current inference backend, NPU availability and active providers."""
    return InferenceInfo(**pipeline.inference_info())


@router.put("/settings/inference", response_model=InferenceInfo)
def update_inference_settings(
    update: InferenceUpdate, pipeline: Pipeline = Depends(get_pipeline)
) -> InferenceInfo:
    """Persist the backend choice (cpu | npu); takes effect after restart."""
    try:
        pipeline.set_inference_backend(update.inference_backend)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    logger.info("Inference backend set to '%s'", update.inference_backend)
    return InferenceInfo(**pipeline.inference_info())
