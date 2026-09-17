import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..providers import PROVIDER_ENV, PROVIDER_TYPES, build_provider, provider_catalog
from ..schemas import ProviderIn, ProviderTestIn
from ..security import mask_key, require
from ..serializers import provider_out
from .deps import audit

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def _provider_from_row(row, transient_key: str = ""):
    params = json.loads(row.params or "{}")
    provider = build_provider(row.provider_type, row.base_url, row.model, row.api_key_env, params)
    if transient_key:
        provider.api_key = transient_key
    return provider


@router.get("")
def list_providers(db: Session = Depends(get_db)):
    rows = db.query(models.ProviderConfig).order_by(models.ProviderConfig.name).all()
    return {
        "provider_types": PROVIDER_TYPES,
        "catalog": provider_catalog(),
        "configured": [provider_out(p) for p in rows],
        "env_vars_present": {name: bool(__import__("os").environ.get(name)) for name in set(PROVIDER_ENV.values())},
    }


@router.post("", status_code=201)
def create_provider(payload: ProviderIn, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    if db.query(models.ProviderConfig).filter_by(name=payload.name).first():
        raise HTTPException(409, "Provider name exists")
    if payload.is_default:
        db.query(models.ProviderConfig).update({"is_default": False})
    p = models.ProviderConfig(
        name=payload.name, provider_type=payload.provider_type, base_url=payload.base_url,
        model=payload.model, api_key_masked=mask_key(payload.api_key), api_key_env=payload.api_key_env,
        params=json.dumps(payload.params), is_default=payload.is_default,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db, auth, "provider.create", p.name, f"type={p.provider_type} key_stored_masked_only=true")
    return {**provider_out(p),
            "note": "Raw API keys are never stored or logged. Set the named server environment variable to use this provider."}


@router.patch("/{provider_id}")
def update_provider(provider_id: int, payload: ProviderIn, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    p = db.get(models.ProviderConfig, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    if payload.is_default:
        db.query(models.ProviderConfig).update({"is_default": False})
    p.provider_type = payload.provider_type
    p.base_url = payload.base_url
    p.model = payload.model
    p.api_key_env = payload.api_key_env
    p.params = json.dumps(payload.params)
    p.is_default = payload.is_default
    if payload.api_key:
        p.api_key_masked = mask_key(payload.api_key)
    db.commit()
    audit(db, auth, "provider.update", p.name)
    return provider_out(p)


@router.delete("/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db), auth=Depends(require("admin"))):
    p = db.get(models.ProviderConfig, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    name = p.name
    db.delete(p)
    db.commit()
    audit(db, auth, "provider.delete", name)
    return {"deleted": provider_id}


@router.post("/{provider_id}/test")
def test_provider(provider_id: int, payload: ProviderTestIn | None = None, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    row = db.get(models.ProviderConfig, provider_id)
    if not row:
        raise HTTPException(404, "Provider not found")
    provider = _provider_from_row(row, payload.api_key if payload else "")
    result = provider.test_connection()
    audit(db, auth, "provider.test", row.name, result.get("detail", ""))
    return {"provider": row.name, "provider_type": row.provider_type, **result}


@router.post("/{provider_id}/models")
def list_models(provider_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    row = db.get(models.ProviderConfig, provider_id)
    if not row:
        raise HTTPException(404, "Provider not found")
    provider = _provider_from_row(row)
    try:
        models_list = provider.list_models()
        return {"provider": row.name, "models": models_list}
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/test")
def test_adhoc(payload: dict, auth=Depends(require("operator"))):
    """Test a provider configuration without persisting it or its key."""
    provider_type = payload.get("provider_type", "")
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(422, f"provider_type must be one of {PROVIDER_TYPES}")
    provider = build_provider(provider_type, payload.get("base_url", ""), payload.get("model", ""),
                              payload.get("api_key_env", ""), payload.get("params") or {})
    if payload.get("api_key"):
        provider.api_key = payload["api_key"]
    result = provider.test_connection()
    return {"provider_type": provider_type, **result,
            "note": "The transient key was used for this test only and was not stored."}


@router.post("/{provider_id}/discover")
def discover_models(provider_id: int, db: Session = Depends(get_db), auth=Depends(require("operator"))):
    return list_models(provider_id, db, auth)
