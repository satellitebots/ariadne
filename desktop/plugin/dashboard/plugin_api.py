"""Routes for Ariadne Desktop, mounted by Hermes at /api/plugins/ariadne/ (the desktop half calls them via ctx.rest).

They only read Ariadne's task store and flip the park flag; the worker does the parking itself, at a step boundary."""
import sys
from pathlib import Path

from fastapi import APIRouter

_ROOT = (Path(__file__).parent / "ariadne_root.txt").read_text(encoding="utf-8").strip()  # written by `ariadne profile`
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ariadne import park  # noqa: E402

router = APIRouter()


@router.get("/status")
async def status():
    return park.status()


@router.post("/park")
async def park_task():
    park.request("desktop")
    return park.status()


@router.post("/resume")
async def resume_task():
    park.resume()
    return park.status()
