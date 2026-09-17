import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..providers import PROVIDER_TYPES
from ..schemas import AgentIn
from ..security import require
from ..serializers import agent_out
from .deps import audit, get_agent_or_404

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _validate_config(payload: AgentIn):
    text = json.dumps(payload.config)
    for forbidden in ('"api_key"', '"apikey"', '"secret"', '"password"'):
        if forbidden in text:
            raise HTTPException(422, "Agent config may not contain raw secrets. Use a provider api_key_env reference.")
    if payload.kind == "llm":
        provider = payload.config.get("provider") or {}
        ptype = provider.get("provider_type", "mock")
        if ptype not in PROVIDER_TYPES:
            raise HTTPException(422, f"provider_type must be one of {PROVIDER_TYPES}")
        if ptype == "mock":
            raise HTTPException(422, "The mock provider is for harness tests only and cannot be registered as an LLM agent. Use a real provider or a local baseline kind.")
    if payload.provider == "mock" and payload.kind == "llm":
        raise HTTPException(422, "Mock inference cannot be presented as LLM performance.")


@router.get("")
def list_agents(
    response: Response,
    q: str = "",
    kind: str = "",
    archived: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Agent).filter_by(archived=archived).order_by(models.Agent.name, models.Agent.version).all()
    if kind:
        rows = [r for r in rows if r.kind == kind]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in f"{r.name} {r.kind} {r.provider} {r.model} {r.description}".lower()]
    response.headers["X-Total-Count"] = str(len(rows))
    return [agent_out(r) for r in rows[offset:offset + limit]]


@router.get("/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    return agent_out(get_agent_or_404(db, agent_id))


@router.get("/{agent_id}/versions")
def agent_versions(agent_id: int, db: Session = Depends(get_db)):
    agent = get_agent_or_404(db, agent_id)
    rows = db.query(models.Agent).filter_by(name=agent.name).order_by(models.Agent.created_at).all()
    return [agent_out(r) for r in rows]


@router.post("", status_code=201)
def create_agent(payload: AgentIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    if db.query(models.Agent).filter_by(name=payload.name, version=payload.version).first():
        raise HTTPException(409, "Agent name+version exists (versions are immutable — create a new version)")
    _validate_config(payload)
    a = models.Agent(
        name=payload.name, kind=payload.kind, version=payload.version, provider=payload.provider,
        model=payload.model, prompt=payload.prompt, system_prompt=payload.system_prompt,
        tools=json.dumps(payload.tools), config=json.dumps(payload.config), description=payload.description,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    audit(db, auth, "agent.create", a.name, f"version={a.version} kind={a.kind}")
    return agent_out(a)


@router.post("/{agent_id}/versions", status_code=201)
def new_agent_version(agent_id: int, payload: AgentIn, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    parent = get_agent_or_404(db, agent_id)
    if payload.name != parent.name:
        raise HTTPException(422, "A new version must keep the same agent name")
    if payload.version == parent.version:
        raise HTTPException(409, "New version must differ from the parent version")
    if db.query(models.Agent).filter_by(name=payload.name, version=payload.version).first():
        raise HTTPException(409, "Version already exists")
    _validate_config(payload)
    a = models.Agent(
        name=payload.name, kind=payload.kind, version=payload.version, provider=payload.provider,
        model=payload.model, prompt=payload.prompt, system_prompt=payload.system_prompt,
        tools=json.dumps(payload.tools), config=json.dumps(payload.config), description=payload.description,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    audit(db, auth, "agent.version", a.name, f"{parent.version}->{a.version}")
    return agent_out(a)


@router.post("/{agent_id}/archive")
def archive_agent(agent_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    a = get_agent_or_404(db, agent_id)
    a.archived = True
    db.commit()
    audit(db, auth, "agent.archive", a.name, a.version)
    return agent_out(a)
