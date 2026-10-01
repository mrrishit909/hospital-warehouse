-- Step 3: questions the warehouse answers (warehouse.py writes each block to results/<name>.csv).
-- Broad ownership: Voluntary non-profit -> Non-profit; Proprietary and Physician -> For-profit; the rest -> Government.

-- name: etl_audit
SELECT * FROM etl_audit ORDER BY date_key;

-- name: versions_by_reason
SELECT change_reason, count(*) AS versions FROM dim_hospital GROUP BY 1 ORDER BY 2 DESC;

-- name: ownership_changes_by_year
SELECT year(valid_from) AS year,
       count(*) FILTER (WHERE change_reason = 'ownership') AS ownership_changes,
       count(*) FILTER (WHERE change_reason = 'ownership' AND ownership IN ('Proprietary', 'Physician')) AS became_for_profit
  FROM dim_hospital WHERE change_reason = 'ownership' GROUP BY 1 ORDER BY 1;

-- name: ownership_change_quality
-- How many recorded ownership changes are real conversions between broad groups, relabels inside a group, or undone
-- by the very next version (likely corrections)?
WITH v AS (
  SELECT hospital_key, ownership, change_reason, lag(ownership) OVER w AS prev, lead(ownership) OVER w AS nxt,
         lead(change_reason) OVER w AS next_reason
    FROM dim_hospital WINDOW w AS (PARTITION BY hospital_key ORDER BY valid_from, hospital_sk)),
b AS (
  SELECT *, CASE WHEN ownership LIKE 'Voluntary%' THEN 'NP' WHEN ownership IN ('Proprietary', 'Physician') THEN 'FP' ELSE 'GOV' END AS g,
            CASE WHEN prev LIKE 'Voluntary%' THEN 'NP' WHEN prev IN ('Proprietary', 'Physician') THEN 'FP' ELSE 'GOV' END AS pg
    FROM v WHERE change_reason = 'ownership')
SELECT count(*) AS ownership_versions,
       count(*) FILTER (WHERE coalesce(nxt = prev AND next_reason = 'ownership', false)) AS undone_by_next_version,  -- NULL-safe: the last version has no next
       count(*) FILTER (WHERE g = pg) AS relabel_within_group,
       count(*) FILTER (WHERE g <> pg) AS change_between_groups,
       count(*) FILTER (WHERE g <> pg AND NOT coalesce(nxt = prev AND next_reason = 'ownership', false)) AS between_groups_not_undone
  FROM b;

-- name: ownership_transitions
WITH broad AS (
  SELECT f.date_key, f.hospital_key,
         CASE WHEN h.ownership LIKE 'Voluntary%' THEN 'Non-profit' WHEN h.ownership IN ('Proprietary', 'Physician') THEN 'For-profit'
              WHEN h.ownership = 'Not Available' THEN 'Unknown' ELSE 'Government' END AS own
    FROM fact_rating f JOIN dim_hospital h USING (hospital_sk))
SELECT a.own AS ownership_2019, b.own AS ownership_2026, count(*) AS hospitals
  FROM broad a JOIN broad b ON a.hospital_key = b.hospital_key
 WHERE a.date_key = (SELECT min(date_key) FROM dim_date) AND b.date_key = (SELECT max(date_key) FROM dim_date)
 GROUP BY 1, 2 ORDER BY 1, 2;

-- name: as_was_vs_as_is
-- Share of rated hospitals with 4-5 stars in the first release, grouped by ownership AS IT WAS then (the version the
-- fact points to) versus AS IT IS NOW (the hospital's current version) - what a Type 1 overwrite would report.
WITH first AS (SELECT * FROM fact_rating WHERE date_key = (SELECT min(date_key) FROM dim_date) AND overall_rating IS NOT NULL),
grp AS (
  SELECT f.overall_rating,
         CASE WHEN was.ownership LIKE 'Voluntary%' THEN 'Non-profit' WHEN was.ownership IN ('Proprietary', 'Physician') THEN 'For-profit' ELSE 'Government' END AS as_was,
         CASE WHEN now.ownership LIKE 'Voluntary%' THEN 'Non-profit' WHEN now.ownership IN ('Proprietary', 'Physician') THEN 'For-profit' ELSE 'Government' END AS as_is
    FROM first f JOIN dim_hospital was ON was.hospital_sk = f.hospital_sk
    JOIN dim_hospital now ON now.hospital_key = f.hospital_key
     AND now.hospital_sk = (SELECT max(hospital_sk) FROM dim_hospital x WHERE x.hospital_key = f.hospital_key))
SELECT o.ownership,
       (SELECT count(*) FROM grp WHERE as_was = o.ownership) AS hospitals_as_was,
       (SELECT round(100.0 * avg((overall_rating >= 4)::int), 1) FROM grp WHERE as_was = o.ownership) AS pct_4_5_stars_as_was,
       (SELECT count(*) FROM grp WHERE as_is = o.ownership) AS hospitals_as_is,
       (SELECT round(100.0 * avg((overall_rating >= 4)::int), 1) FROM grp WHERE as_is = o.ownership) AS pct_4_5_stars_as_is
  FROM (VALUES ('Non-profit'), ('For-profit'), ('Government')) o(ownership);

-- name: rural_emergency_hospitals
SELECT h.facility_id, h.name, h.state, h.valid_from AS first_release_as_reh, l.old_facility_id, l.rule,
       (SELECT hospital_type FROM dim_hospital o WHERE o.facility_id = l.old_facility_id ORDER BY valid_from DESC LIMIT 1) AS previous_type
  FROM dim_hospital h LEFT JOIN hospital_lineage l ON l.new_facility_id = h.facility_id
 WHERE h.hospital_type = 'Rural Emergency Hospital' AND h.change_reason IN ('first seen', 'new facility ID')
 ORDER BY h.valid_from, h.state;

-- name: hospitals_by_release
SELECT d.date_key, count(*) AS hospitals, count(f.overall_rating) AS rated,
       count(*) FILTER (WHERE h.hospital_type = 'Rural Emergency Hospital') AS rural_emergency,
       count(*) FILTER (WHERE h.hospital_type = 'Acute Care - Veterans Administration') AS va,
       round(avg(f.overall_rating), 2) AS mean_rating
  FROM fact_rating f JOIN dim_date d USING (date_key) JOIN dim_hospital h USING (hospital_sk)
 GROUP BY 1 ORDER BY 1;

-- name: lineage
SELECT * FROM hospital_lineage ORDER BY state, city;
