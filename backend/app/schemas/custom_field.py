import uuid
from typing import Any
from pydantic import BaseModel, Field, field_validator

VALID_ENTITY_TYPES = {"token", "product", "party"}
VALID_FIELD_TYPES = {"text", "number", "select", "date", "boolean"}


def _slugify_key(s: str) -> str:
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in s.strip().lower())
    out = "_".join(p for p in out.split("_") if p)  # collapse repeats
    return out[:60] or "field"


class CustomFieldDefinitionBase(BaseModel):
    entity_type: str = "token"
    field_key: str | None = None       # auto-derived from label if omitted
    label: str
    field_type: str = "text"
    unit: str | None = None
    options: list[str] | None = None
    required: bool = False
    show_on_slip: bool = True
    sort_order: int = 0
    is_active: bool = True

    @field_validator("entity_type")
    @classmethod
    def _v_entity(cls, v: str) -> str:
        v = (v or "token").lower()
        if v not in VALID_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {sorted(VALID_ENTITY_TYPES)}")
        return v

    @field_validator("field_type")
    @classmethod
    def _v_type(cls, v: str) -> str:
        v = (v or "text").lower()
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of {sorted(VALID_FIELD_TYPES)}")
        return v


class CustomFieldDefinitionCreate(CustomFieldDefinitionBase):
    pass


class CustomFieldDefinitionUpdate(BaseModel):
    label: str | None = None
    field_type: str | None = None
    unit: str | None = None
    options: list[str] | None = None
    required: bool | None = None
    show_on_slip: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CustomFieldDefinitionOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    field_key: str
    label: str
    field_type: str
    unit: str | None = None
    options: list[Any] | None = None
    required: bool
    show_on_slip: bool
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}
