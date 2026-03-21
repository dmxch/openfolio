"""API route for sector/industry taxonomy."""

from fastapi import APIRouter, Depends

from auth import get_current_user
from services.sector_mapping import (
    SECTOR_ORDER,
    FINVIZ_SECTORS,
    SECTORS_WITH_INDUSTRIES,
    MULTI_SECTOR_INDUSTRIES,
)

router = APIRouter(prefix="/api/sectors", tags=["taxonomy"])


@router.get("/taxonomy")
async def get_taxonomy(user=Depends(get_current_user)):
    return {
        "sectors": SECTOR_ORDER,
        "finviz_sectors": FINVIZ_SECTORS,
        "multi_sector_industries": MULTI_SECTOR_INDUSTRIES,
        "sectors_with_industries": SECTORS_WITH_INDUSTRIES,
    }
