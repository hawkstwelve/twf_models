from fastapi import FastAPI

from .api.v2 import router as v2_router

app = FastAPI(
    title="TWF Models API (V2)",
    version="0.1.0",
)

app.include_router(v2_router)

@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
