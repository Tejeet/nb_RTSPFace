"""Similarity search: upload a face image, find the closest stored faces."""

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import face_to_summary, get_pipeline
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import SearchMatch, SearchResponse

logger = get_logger("api.search")

router = APIRouter(prefix="/api", tags=["search"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/search", response_model=SearchResponse)
async def search_similar_faces(
    file: UploadFile = File(...),
    top_k: int = Query(default=10, ge=1, le=50),
    pipeline: Pipeline = Depends(get_pipeline),
) -> SearchResponse:
    """Detect the largest face in the uploaded image and search FAISS."""
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    detections = pipeline.models.detect(image)
    if not detections:
        return SearchResponse(query_faces_detected=0, matches=[])

    # Use the largest detected face as the query.
    query_face = max(detections, key=lambda d: d.bbox[2] * d.bbox[3])
    embedding = pipeline.models.embed(image, query_face.kps)

    results = pipeline.vector_store.search(embedding, top_k=top_k)
    faces = pipeline.repository.get_faces_by_ids([face_id for face_id, _ in results])
    similarity_by_id = dict(results)

    matches = [
        SearchMatch(face=face_to_summary(face), similarity=round(similarity_by_id[face.id], 4))
        for face in faces
    ]
    logger.info("Search: %d detections, %d matches returned", len(detections), len(matches))
    return SearchResponse(query_faces_detected=len(detections), matches=matches)
