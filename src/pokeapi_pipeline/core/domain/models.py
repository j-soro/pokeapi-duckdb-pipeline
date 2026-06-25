"""Staging schema; one struct per staging table."""

import msgspec


class Pokemon(msgspec.Struct, frozen=True):
    """A pokemon row."""

    id: int
    name: str
    height: int
    weight: int
    base_experience: int | None
    order: int
    is_default: bool
    species_id: int
    types: tuple[str, ...]
    abilities: tuple[str, ...]
    sprite_front_default: str | None
    sprite_back_default: str | None
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int


class PokemonSpecies(msgspec.Struct, frozen=True):
    """A pokemon-species row."""

    id: int
    name: str
    order: int
    generation_id: int
    evolution_chain_id: int
    evolves_from_id: int | None
    is_legendary: bool
    is_mythical: bool
    is_baby: bool
    capture_rate: int
    base_happiness: int | None
    gender_rate: int
    hatch_counter: int | None
    has_gender_differences: bool
    forms_switchable: bool
    growth_rate: str
    color: str
    shape: str | None
    habitat: str | None
    egg_groups: tuple[str, ...]
    flavor_text: str | None


class PokemonType(msgspec.Struct, frozen=True):
    """A type row."""

    id: int
    name: str
    generation_id: int
    move_damage_class: str | None
    double_damage_to: tuple[str, ...]
    double_damage_from: tuple[str, ...]
    half_damage_to: tuple[str, ...]
    half_damage_from: tuple[str, ...]
    no_damage_to: tuple[str, ...]
    no_damage_from: tuple[str, ...]


class PokemonMove(msgspec.Struct, frozen=True):
    """A move row."""

    id: int
    name: str
    power: int | None
    accuracy: int | None
    pp: int | None
    priority: int
    effect_chance: int | None
    type_id: int
    damage_class: str
    target: str
    generation_id: int
