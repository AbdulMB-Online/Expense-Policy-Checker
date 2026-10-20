"""HTTP endpoints for workspace."""

from fastapi import APIRouter, Depends

from backend.api.dependencies import Services, current_user, get_services, reviewer
from backend.api.responses import file_response

router = APIRouter()


@router.get("/api/datasets")
def datasets(
    user=Depends(current_user),
    services: Services = Depends(get_services),
):
    return services.workspace.datasets.datasets(user)


@router.get("/api/check-runs/{run_id}")
def check_run(
    run_id: str,
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    return services.workspace.checks.check_run(run_id)


@router.get("/api/artifacts")
def artifacts(
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    return services.workspace.artifacts.artifacts()


@router.get("/api/artifacts/{artifact_id}")
def download_artifact(
    artifact_id: str,
    user=Depends(reviewer),
    services: Services = Depends(get_services),
):
    name, media_type, contents = services.workspace.artifacts.artifact(artifact_id)
    return file_response(name, media_type, contents)
