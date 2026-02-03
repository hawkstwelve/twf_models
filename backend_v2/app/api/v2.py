from fastapi import APIRouter

router = APIRouter(prefix="/api/v2", tags=["v2"])


@router.get("/models")
def list_models() -> list[dict[str, str]]:
    return [
        {
            "id": "hrrr",
            "name": "HRRR",
        }
    ]
