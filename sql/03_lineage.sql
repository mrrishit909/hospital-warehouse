-- Find hospitals that changed CMS facility ID (e.g. a conversion to a Rural Emergency Hospital gets a new ID).
-- Candidates: the old ID left the data before the new ID first appeared, in the same city and state.
-- Link when the names share at least half their distinctive words, or when the new facility is a Rural Emergency
-- Hospital with exactly one candidate in its city (several were renamed on conversion).
CREATE OR REPLACE TABLE seen AS
SELECT lpad(facility_id, 6, '0') AS facility_id, CAST(regexp_extract(filename, '(\d{4}-\d{2}-\d{2})', 1) AS date) AS snap,
       upper(trim(city)) AS city, upper(trim(state)) AS state, trim(hospital_type) AS hospital_type,
       list_distinct(list_filter(string_split(regexp_replace(upper(name), '[^A-Z0-9 ]', '', 'g'), ' '),
         w -> w <> '' AND w NOT IN ('HOSPITAL', 'MEDICAL', 'CENTER', 'CENTERS', 'REGIONAL', 'HEALTH', 'HEALTHCARE', 'INC', 'THE',
                                     'OF', 'AND', 'COMMUNITY', 'SYSTEM', 'LLC', 'CAMPUS'))) AS words,
       upper(name) AS name
  FROM read_csv('{snapshots}/general_*.csv', all_varchar = true, header = true, filename = true);

CREATE OR REPLACE TABLE span AS
SELECT facility_id, min(snap) AS first_seen, max(snap) AS last_seen,
       arg_max(city, snap) AS city, arg_max(state, snap) AS state, arg_max(words, snap) AS words, arg_max(name, snap) AS name,
       arg_min(hospital_type, snap) AS first_type
  FROM seen GROUP BY facility_id;

CREATE OR REPLACE TABLE lineage_candidates AS
SELECT n.facility_id AS new_facility_id, o.facility_id AS old_facility_id, n.name AS new_name, o.name AS old_name, n.city, n.state,
       n.first_type AS new_type,
       len(list_intersect(n.words, o.words)) / greatest(len(list_distinct(list_concat(n.words, o.words))), 1) AS name_overlap,
       count(*) OVER (PARTITION BY n.facility_id) AS candidates
  FROM span n JOIN span o ON o.city = n.city AND o.state = n.state AND o.facility_id <> n.facility_id
 WHERE n.first_seen > (SELECT min(snap) FROM seen)                         -- genuinely new, not present from the start
   AND o.last_seen < n.first_seen
   -- usually within a year; for a Rural Emergency Hospital, any time since the programme began (January 2023),
   -- because CMS only started listing them in late 2025, long after many converted
   AND o.last_seen >= CASE WHEN n.first_type = 'Rural Emergency Hospital' THEN DATE '2023-01-01'
                           ELSE n.first_seen - INTERVAL 365 DAY END;

INSERT INTO hospital_lineage
SELECT old_facility_id, new_facility_id,
       CASE WHEN name_overlap >= 0.5 THEN 'same city, names share at least half their words'
            ELSE 'same city, only candidate for a new Rural Emergency Hospital' END,
       old_name, new_name, city, state
  FROM lineage_candidates
 WHERE name_overlap >= 0.5 OR (new_type = 'Rural Emergency Hospital' AND candidates = 1)
QUALIFY row_number() OVER (PARTITION BY new_facility_id ORDER BY name_overlap DESC) = 1
    AND row_number() OVER (PARTITION BY old_facility_id ORDER BY name_overlap DESC) = 1;
