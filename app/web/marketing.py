from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.db.models import User
from app.web.deps import get_current_user
from app.web.templating import templates

router = APIRouter(tags=["marketing"])


@router.get("/")
async def home(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/projects")
    return templates.TemplateResponse(request, "marketing_home.html", {"user": None})


@router.get("/pricing")
async def pricing(request: Request, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(request, "marketing_pricing.html", {"user": user})


@router.get("/support")
async def support(request: Request, sent: bool = False, user: User | None = Depends(get_current_user)):
    return templates.TemplateResponse(request, "marketing_support.html", {"user": user, "sent": sent})


@router.post("/support/contact")
async def support_contact(
    name: str = Form(""),
    email: str = Form(...),
    topic: str = Form(""),
    message: str = Form(""),
) -> RedirectResponse:
    return RedirectResponse("/support?sent=1", status_code=303)
