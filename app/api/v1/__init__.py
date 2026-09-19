"""API v1 master router inclusion."""
from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.donors import router as donors_router
from app.api.v1.requests import router as requests_router
from app.api.v1.matches import router as matches_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.events import router as events_router
from app.api.v1.notices import router as notices_router
from app.api.v1.logs import router as logs_router
from app.api.v1.communications import router as communications_router
from app.api.v1.users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(donors_router)
api_router.include_router(requests_router)
api_router.include_router(matches_router)
api_router.include_router(inventory_router)
api_router.include_router(events_router)
api_router.include_router(notices_router)
api_router.include_router(logs_router)
api_router.include_router(communications_router)
api_router.include_router(users_router)
