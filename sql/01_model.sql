-- Step 2: a Kimball star schema in DuckDB.
--   dim_hospital   one row per VERSION of a hospital. Type 2 (new row, dated) for ownership, hospital type and emergency
--                  services, which change for real reasons. Type 1 (overwritten in every version) for name and
--                  address, whose changes are mostly cosmetic ("ST VINCENT'S" -> "ST. VINCENT'S").
--   hospital_key   a durable key that survives a change of CMS facility ID (a Rural Emergency Hospital conversion
--                  gets a new ID); see hospital_lineage.
--   fact_rating    periodic snapshot: one row per hospital per CMS release, with the overall star rating.
CREATE SEQUENCE IF NOT EXISTS hospital_sk_seq;
CREATE SEQUENCE IF NOT EXISTS hospital_key_seq;

CREATE TABLE dim_date (
  date_key      date PRIMARY KEY,
  year          smallint NOT NULL,
  quarter       tinyint NOT NULL,
  release_no    smallint NOT NULL UNIQUE           -- 1st, 2nd, ... CMS release in the warehouse
);

CREATE TABLE hospital_lineage (                    -- old facility ID -> new facility ID, same hospital
  old_facility_id varchar(6) NOT NULL,
  new_facility_id varchar(6) NOT NULL PRIMARY KEY,
  rule            varchar NOT NULL,
  old_name        varchar, new_name varchar, city varchar, state varchar(2)
);

CREATE TABLE dim_hospital (
  hospital_sk        integer PRIMARY KEY DEFAULT nextval('hospital_sk_seq'),
  hospital_key       integer NOT NULL,             -- durable key: same hospital across versions and ID changes
  facility_id        varchar(6) NOT NULL,          -- CMS certification number (business key)
  name               varchar NOT NULL,             -- Type 1
  address            varchar, city varchar, state varchar(2), zip varchar(5), county varchar,   -- Type 1
  hospital_type      varchar NOT NULL,             -- Type 2
  ownership          varchar NOT NULL,             -- Type 2
  emergency_services boolean,                      -- Type 2
  valid_from         date NOT NULL,
  valid_to           date,                         -- NULL = still current
  is_current         boolean NOT NULL,
  change_reason      varchar NOT NULL              -- 'first seen', 'ownership', 'type', 'emergency', 'returned'
);

CREATE TABLE fact_rating (
  date_key       date NOT NULL REFERENCES dim_date (date_key),
  hospital_sk    integer NOT NULL REFERENCES dim_hospital (hospital_sk),
  hospital_key   integer NOT NULL,
  overall_rating tinyint CHECK (overall_rating BETWEEN 1 AND 5),   -- NULL = "Not Available"
  PRIMARY KEY (date_key, hospital_key)
);

CREATE TABLE etl_audit (
  date_key date PRIMARY KEY, rows_in integer, new_hospitals integer, new_versions integer,
  closed integer, reopened integer, type1_updates integer, facts integer
);
