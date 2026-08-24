from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.onprem_client import OnPremLLMError
from app.network_diagram import NetworkDiagram, generate_network_diagram
from app.sheets import ParsedWorkbook, SheetParseError, parse_spreadsheet

router = APIRouter(prefix="/api/sheets", tags=["sheets"])


@router.post("/parse", response_model=ParsedWorkbook)
async def parse_sheet(file: UploadFile) -> ParsedWorkbook:
    content = await file.read()
    try:
        return parse_spreadsheet(file.filename or "upload", content)
    except SheetParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class DiagramRequest(BaseModel):
    headers: list[str]
    rows: list[list[str]]


@router.post("/diagram", response_model=NetworkDiagram)
async def diagram_sheet(
    body: DiagramRequest, settings: Settings = Depends(get_settings)
) -> NetworkDiagram:
    try:
        return await generate_network_diagram(body.headers, body.rows, settings)
    except OnPremLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
