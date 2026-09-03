"""CragPal Cloud Asset API v1. No arbitrary COS proxy. BUILD != PUBLISHED."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .contract import ContractError, is_release_id, is_safe_id
from .memory_store import MemoryStore
from .store import NotFound, StorageFailure, StorageUnavailable


def _load_store():
    mode = (os.environ.get("CRAGPAL_ASSET_STORE") or "cos").strip().lower()
    if mode == "memory":
        return MemoryStore.example()
    from .cos_store import CosStore

    return CosStore.from_env()


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="CragPal Cloud Asset API", version="v1")
    app.state.injected_store = store
    app.state.resolved_store = None

    def resolve_store():
        if app.state.injected_store is not None:
            return app.state.injected_store
        if app.state.resolved_store is not None:
            return app.state.resolved_store
        try:
            app.state.resolved_store = _load_store()
        except StorageUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail="asset store is not configured",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="asset store is not configured",
            ) from exc
        return app.state.resolved_store

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/walls")
    def list_walls() -> dict:
        return resolve_store().catalog()

    @app.get("/v1/walls/{wall_id}/manifest")
    def wall_manifest(wall_id: str) -> dict:
        _reject_unsafe_wall(wall_id)
        return resolve_store().manifest(wall_id)

    @app.get("/v1/walls/{wall_id}/releases/{release_id}/manifest")
    def wall_release_manifest(wall_id: str, release_id: str) -> dict:
        _reject_unsafe_wall(wall_id)
        _reject_unsafe_release(release_id)
        return resolve_store().manifest_for_release(wall_id, release_id)

    @app.get("/v1/walls/{wall_id}/releases/{release_id}/assets/{asset_id}")
    def wall_release_asset(wall_id: str, release_id: str, asset_id: str) -> Response:
        _reject_unsafe_wall(wall_id)
        _reject_unsafe_release(release_id)
        _reject_unsafe_asset(asset_id)
        payload = resolve_store().asset_bytes(wall_id, release_id, asset_id)
        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers={
                "X-CragPal-Asset-Id": asset_id,
                "X-CragPal-Release-Id": release_id,
                "Content-Length": str(len(payload)),
            },
        )

    @app.exception_handler(NotFound)
    async def not_found_handler(_request: Request, _exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @app.exception_handler(StorageUnavailable)
    async def storage_unavailable_handler(_request: Request, _exc: StorageUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "asset store is not configured"})

    @app.exception_handler(StorageFailure)
    async def storage_failure_handler(_request: Request, _exc: StorageFailure) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "asset store failed"})

    @app.exception_handler(ContractError)
    async def contract_error_handler(_request: Request, _exc: ContractError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "invalid published contract document"})

    return app


def _reject_unsafe_wall(wall_id: str) -> None:
    if not is_safe_id(wall_id):
        raise HTTPException(status_code=400, detail="invalid wallId")


def _reject_unsafe_release(release_id: str) -> None:
    if not is_release_id(release_id):
        raise HTTPException(status_code=400, detail="invalid releaseId")


def _reject_unsafe_asset(asset_id: str) -> None:
    if not is_safe_id(asset_id):
        raise HTTPException(status_code=400, detail="invalid assetId")


app = create_app()
