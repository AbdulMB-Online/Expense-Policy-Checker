"""JSON request models for session and expense operations."""

from typing import Literal

from pydantic import BaseModel, Field


class LoginInput(BaseModel):
    user_id: str = Field(max_length=100)


class ReviewInput(BaseModel):
    run_id: str = Field(max_length=100)
    revision_id: str = Field(max_length=100)
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str = Field(default="", max_length=2000)


class OwnerInput(BaseModel):
    user_id: str = Field(max_length=100)
