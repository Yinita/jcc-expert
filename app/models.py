from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Mode = Literal['nature', 'orange']


class Unit(BaseModel):
    hero_id: str = Field(min_length=1, max_length=32)
    stars: int | None = Field(default=None, ge=1, le=4)
    item_ids: list[str] = Field(default_factory=list, max_length=10)


class GameState(BaseModel):
    model_config = ConfigDict(extra='ignore')
    mode: Mode
    patch: str = Field(default='18.6', max_length=30)
    stage: str | None = Field(default=None, pattern=r'^\d{1,2}-\d{1,2}$')
    hp: int | None = Field(default=None, ge=0, le=999)
    gold: int | None = Field(default=None, ge=0, le=10000)
    level: int | None = Field(default=None, ge=1, le=20)
    xp: int | None = Field(default=None, ge=0, le=10000)
    board: list[Unit] = Field(default_factory=list, max_length=40)
    bench: list[Unit] = Field(default_factory=list, max_length=40)
    shop: list[str | None] = Field(default_factory=list, max_length=10)
    item_ids: list[str] = Field(default_factory=list, max_length=100)
    augment_ids: list[str] = Field(default_factory=list, max_length=10)
    offered_augment_ids: list[str] = Field(default_factory=list, max_length=10)
    orange_card_ids: list[str] = Field(default_factory=list, max_length=3)
    portal: str | None = Field(default=None, max_length=100)
    confirmed: bool = False
    screenshot_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    match_id: str | None = Field(default=None, max_length=100)
    is_demo: bool = False


class ResultEvent(BaseModel):
    state: GameState
    placement: int = Field(ge=1, le=8)
    match_id: str = Field(min_length=1, max_length=100)
    selected_candidate_id: str | None = Field(default=None, max_length=100)


class TrainRequest(BaseModel):
    mode: Mode = 'nature'
    patch: str = Field(default='18.6', max_length=30)


class NegativeRegion(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=60)
    confirmed: bool = False
    not_fields: list[Literal['stage', 'gold', 'hp', 'level']] = Field(default_factory=list, max_length=4)


class RecognitionFeedback(BaseModel):
    state: GameState
    layout_profile: dict
    negative_regions: list[NegativeRegion] = Field(default_factory=list, max_length=50)
    absent_fields: list[Literal['stage', 'gold', 'hp', 'level']] = Field(default_factory=list, max_length=4)
    all_fields_reviewed: bool = False
    replace_annotations: bool = False
