"""Style profiles live in the LangGraph store (namespace ("users", uid, "style_profiles")) so the
write_section node reads them directly through `runtime.store`."""

import uuid

from fastapi import APIRouter, Response

from app.api import schemas
from app.api.deps import ContainerDep, UserDep
from app.core.errors import AppError, NotFound
from app.db.models_app import User
from app.graph.util import now_iso

router = APIRouter(prefix="/style-profiles", tags=["style-profiles"])
MAX_PROFILES = 20


def _ns(user_id) -> tuple[str, ...]:
    return ("users", str(user_id), "style_profiles")


async def _set_default(c, user_id, profile_id: str | None) -> None:
    async with c.sessions.begin() as s:
        u = await s.get(User, user_id, with_for_update=True)
        u.settings = {**(u.settings or {}), "default_style_profile_id": profile_id}


def _out(item, default_id: str | None) -> schemas.StyleProfileOut:
    v = item.value
    return schemas.StyleProfileOut(id=item.key, name=v["name"], examples=v["examples"],
                                   is_default=item.key == default_id, updated_at=v.get("updated_at", ""))


@router.get("", response_model=list[schemas.StyleProfileOut])
async def list_profiles(user: UserDep, c: ContainerDep) -> list[schemas.StyleProfileOut]:
    items = await c.store.asearch(_ns(user.id), limit=MAX_PROFILES)
    default_id = (user.settings or {}).get("default_style_profile_id")
    return sorted((_out(i, default_id) for i in items), key=lambda p: p.name.lower())


@router.post("", status_code=201, response_model=schemas.StyleProfileOut)
async def create_profile(body: schemas.StyleProfileIn, user: UserDep, c: ContainerDep) -> schemas.StyleProfileOut:
    if len(await c.store.asearch(_ns(user.id), limit=MAX_PROFILES)) >= MAX_PROFILES:
        raise AppError(f"You can have at most {MAX_PROFILES} style profiles.", code="too_many", status_code=422)
    pid = uuid.uuid4().hex[:12]
    await c.store.aput(_ns(user.id), pid, {"name": body.name, "examples": [e[:20000] for e in body.examples],
                                           "updated_at": now_iso()})
    if body.is_default:
        await _set_default(c, user.id, pid)
    item = await c.store.aget(_ns(user.id), pid)
    return _out(item, pid if body.is_default else (user.settings or {}).get("default_style_profile_id"))


@router.put("/{profile_id}", response_model=schemas.StyleProfileOut)
async def update_profile(profile_id: str, body: schemas.StyleProfileIn, user: UserDep, c: ContainerDep
                         ) -> schemas.StyleProfileOut:
    if await c.store.aget(_ns(user.id), profile_id) is None:
        raise NotFound("Style profile not found.")
    await c.store.aput(_ns(user.id), profile_id, {"name": body.name, "examples": [e[:20000] for e in body.examples],
                                                  "updated_at": now_iso()})
    default_id = (user.settings or {}).get("default_style_profile_id")
    if body.is_default and default_id != profile_id:
        await _set_default(c, user.id, profile_id)
        default_id = profile_id
    elif not body.is_default and default_id == profile_id:
        await _set_default(c, user.id, None)
        default_id = None
    return _out(await c.store.aget(_ns(user.id), profile_id), default_id)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, user: UserDep, c: ContainerDep) -> Response:
    if await c.store.aget(_ns(user.id), profile_id) is None:
        raise NotFound("Style profile not found.")
    await c.store.adelete(_ns(user.id), profile_id)
    if (user.settings or {}).get("default_style_profile_id") == profile_id:
        await _set_default(c, user.id, None)
    return Response(status_code=204)
