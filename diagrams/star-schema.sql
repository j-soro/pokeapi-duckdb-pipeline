-- Transform Plan — analytics (gold) star schema.
-- Derived entirely from staging (silver); rebuildable, no migrations.
-- Serves the team-building optimizer (see openspec transform-pokeapi/design.md §2).
-- Source for the diagram: open in a SQL IDE and render an ER/diagram from the DDL.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Dimensions -----------------------------------------------------------------

-- The 18 types.
CREATE TABLE analytics.dim_type (
    type_id  INTEGER PRIMARY KEY,
    name     VARCHAR NOT NULL
);

-- Species attributes; evolution family = evolution_chain_id.
CREATE TABLE analytics.dim_species (
    species_id               INTEGER PRIMARY KEY,
    name                     VARCHAR NOT NULL,
    evolution_chain_id       INTEGER NOT NULL,
    evolves_from_species_id  INTEGER REFERENCES analytics.dim_species (species_id),
    is_legendary             BOOLEAN NOT NULL,
    is_mythical              BOOLEAN NOT NULL,
    generation_id            INTEGER NOT NULL
);

-- Moves; power/accuracy null for status moves. damage_class picks attack vs sp_atk.
CREATE TABLE analytics.dim_move (
    move_id       INTEGER PRIMARY KEY,
    name          VARCHAR NOT NULL,
    type_id       INTEGER NOT NULL REFERENCES analytics.dim_type (type_id),
    power         INTEGER,
    accuracy      INTEGER,
    damage_class  VARCHAR NOT NULL,  -- physical | special | status
    pp            INTEGER
);

-- Fact -----------------------------------------------------------------------

-- Grain: one pokemon. Stats are the optimizer's measures; base_stat_total = sum of the six.
CREATE TABLE analytics.fact_pokemon (
    pokemon_id       INTEGER PRIMARY KEY,
    species_id       INTEGER NOT NULL REFERENCES analytics.dim_species (species_id),
    name             VARCHAR NOT NULL,
    generation_id    INTEGER NOT NULL,  -- format/dex filter
    hp               INTEGER NOT NULL,
    attack           INTEGER NOT NULL,
    defense          INTEGER NOT NULL,
    sp_atk           INTEGER NOT NULL,
    sp_def           INTEGER NOT NULL,
    speed            INTEGER NOT NULL,
    base_stat_total  INTEGER NOT NULL,
    height           INTEGER NOT NULL,
    weight           INTEGER NOT NULL
);

-- Bridges (many-to-many) -----------------------------------------------------

-- A pokemon's 1-2 types (slot ordinal). STAB + defensive profile.
CREATE TABLE analytics.bridge_pokemon_type (
    pokemon_id  INTEGER NOT NULL REFERENCES analytics.fact_pokemon (pokemon_id),
    type_id     INTEGER NOT NULL REFERENCES analytics.dim_type (type_id),
    slot        SMALLINT NOT NULL,  -- 1 | 2
    PRIMARY KEY (pokemon_id, type_id)
);

-- The learnset: which moves a pokemon can use (firepower candidates).
CREATE TABLE analytics.bridge_pokemon_move (
    pokemon_id  INTEGER NOT NULL REFERENCES analytics.fact_pokemon (pokemon_id),
    move_id     INTEGER NOT NULL REFERENCES analytics.dim_move (move_id),
    PRIMARY KEY (pokemon_id, move_id)
);

-- The 18x18 effectiveness matrix: multiplier in {0.0, 0.5, 1.0, 2.0}.
CREATE TABLE analytics.bridge_type_effectiveness (
    attacking_type_id  INTEGER NOT NULL REFERENCES analytics.dim_type (type_id),
    defending_type_id  INTEGER NOT NULL REFERENCES analytics.dim_type (type_id),
    multiplier         DOUBLE NOT NULL,
    PRIMARY KEY (attacking_type_id, defending_type_id)
);
