"""Person enrollment and management.

Enroll a person from a photo + name + employee id: the largest face in the
photo is detected, embedded, stored, and added to the recognition index so
subsequent captures of that person are labelled with their name.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_pipeline
from app.db.models import Person
from app.logging_setup import get_logger
from app.pipeline.orchestrator import Pipeline
from app.schemas import EnrollResponse, MessageResponse, PersonListResponse, PersonSummary

logger = get_logger("api.persons")

router = APIRouter(prefix="/api", tags=["persons"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _to_summary(person: Person) -> PersonSummary:
    return PersonSummary(
        id=person.id,
        name=person.name,
        employee_id=person.employee_id,
        created_at=person.created_at,
        photo_url=f"/api/persons/{person.id}/photo",
    )


@router.get("/persons", response_model=PersonListResponse)
def list_persons(pipeline: Pipeline = Depends(get_pipeline)) -> PersonListResponse:
    """All enrolled persons, newest first."""
    persons = pipeline.repository.list_persons()
    return PersonListResponse(items=[_to_summary(p) for p in persons], total=len(persons))


@router.post("/persons", response_model=EnrollResponse)
async def enroll_person(
    name: str = Form(...),
    employee_id: str = Form(...),
    file: UploadFile = File(...),
    pipeline: Pipeline = Depends(get_pipeline),
) -> EnrollResponse:
    """Enroll a person: detect + embed the face in the photo and index it."""
    name = name.strip()
    employee_id = employee_id.strip()
    if not name or not employee_id:
        raise HTTPException(status_code=422, detail="Name and employee ID are required")

    if pipeline.repository.get_person_by_employee_id(employee_id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Employee ID '{employee_id}' is already enrolled"
        )

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    detections = pipeline.models.detect(image)
    if not detections:
        raise HTTPException(status_code=422, detail="No face detected in the photo")

    # Enroll on the largest (most prominent) face.
    face = max(detections, key=lambda d: d.bbox[2] * d.bbox[3])
    embedding = pipeline.models.embed(image, face.kps)

    person_uuid = str(uuid.uuid4())
    photo_path = pipeline.settings.persons_dir / f"{person_uuid}.jpg"
    embedding_path = pipeline.settings.persons_dir / f"{person_uuid}.npy"
    cv2.imwrite(str(photo_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    np.save(embedding_path, embedding)

    person = pipeline.repository.insert_person(
        Person(
            name=name,
            employee_id=employee_id,
            created_at=datetime.now(UTC),
            photo_path=str(photo_path),
            embedding_path=str(embedding_path),
        )
    )
    pipeline.person_manager.enroll(person.id, embedding)
    logger.info("Enrolled person id=%d name=%s employee_id=%s", person.id, name, employee_id)

    return EnrollResponse(
        person=_to_summary(person),
        message=f"{name} enrolled ({len(detections)} face(s) in photo; used the largest)",
    )


@router.get("/persons/{person_id}/photo")
def get_person_photo(person_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> FileResponse:
    """The enrollment photo for a person."""
    person = pipeline.repository.get_person(person_id)
    if person is None or not Path(person.photo_path).exists():
        raise HTTPException(status_code=404, detail="Person or photo not found")
    return FileResponse(person.photo_path, media_type="image/jpeg")


@router.delete("/persons/{person_id}", response_model=MessageResponse)
def delete_person(person_id: int, pipeline: Pipeline = Depends(get_pipeline)) -> MessageResponse:
    """Delete an enrolled person and remove them from the recognition index."""
    person = pipeline.repository.delete_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    pipeline.person_manager.remove(person_id)
    for path_str in (person.photo_path, person.embedding_path):
        Path(path_str).unlink(missing_ok=True)
    logger.info("Deleted person id=%d name=%s", person_id, person.name)
    return MessageResponse(message=f"{person.name} removed")
