-- Warehouse schema: one staging table per struct in models.py.
-- Idempotent; staging is rebuildable from raw, so there are no migrations.

-- bronze: faithful captured payloads; the cross-run cache and resume checkpoint.
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.records (
    key VARCHAR PRIMARY KEY,
    entity_type VARCHAR NOT NULL,
    payload JSON NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL
);

-- silver: typed, validated, reshaped projection of raw.
CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.pokemon (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    height BIGINT NOT NULL,
    weight BIGINT NOT NULL,
    base_experience BIGINT,
    "order" BIGINT NOT NULL,
    is_default BOOLEAN NOT NULL,
    species_id BIGINT NOT NULL,
    types VARCHAR[] NOT NULL,
    abilities VARCHAR[] NOT NULL,
    moves VARCHAR[] NOT NULL,
    sprite_front_default VARCHAR,
    sprite_back_default VARCHAR,
    hp BIGINT NOT NULL,
    attack BIGINT NOT NULL,
    defense BIGINT NOT NULL,
    special_attack BIGINT NOT NULL,
    special_defense BIGINT NOT NULL,
    speed BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.species (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    "order" BIGINT NOT NULL,
    generation_id BIGINT NOT NULL,
    evolution_chain_id BIGINT NOT NULL,
    evolves_from_id BIGINT,
    is_legendary BOOLEAN NOT NULL,
    is_mythical BOOLEAN NOT NULL,
    is_baby BOOLEAN NOT NULL,
    capture_rate BIGINT NOT NULL,
    base_happiness BIGINT,
    gender_rate BIGINT NOT NULL,
    hatch_counter BIGINT,
    has_gender_differences BOOLEAN NOT NULL,
    forms_switchable BOOLEAN NOT NULL,
    growth_rate VARCHAR NOT NULL,
    color VARCHAR NOT NULL,
    shape VARCHAR,
    habitat VARCHAR,
    egg_groups VARCHAR[] NOT NULL,
    flavor_text VARCHAR
);

CREATE TABLE IF NOT EXISTS staging.type (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    generation_id BIGINT NOT NULL,
    move_damage_class VARCHAR,
    double_damage_to VARCHAR[] NOT NULL,
    double_damage_from VARCHAR[] NOT NULL,
    half_damage_to VARCHAR[] NOT NULL,
    half_damage_from VARCHAR[] NOT NULL,
    no_damage_to VARCHAR[] NOT NULL,
    no_damage_from VARCHAR[] NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.move (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    power BIGINT,
    accuracy BIGINT,
    pp BIGINT,
    priority BIGINT NOT NULL,
    effect_chance BIGINT,
    type_id BIGINT NOT NULL,
    damage_class VARCHAR NOT NULL,
    target VARCHAR NOT NULL,
    generation_id BIGINT NOT NULL
);

-- meta: run lineage / audit; one row per pipeline invocation.
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.runs (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    scope_limit BIGINT NOT NULL,
    stages VARCHAR[] NOT NULL,
    raw_written BIGINT,
    staging_written BIGINT,
    error VARCHAR
);
