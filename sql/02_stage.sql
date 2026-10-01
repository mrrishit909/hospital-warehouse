-- Normalise one snapshot file: trim, collapse spaces, upper-case, so cosmetic differences don't look like changes.
-- {snap} and {file} are filled in by warehouse.py.
CREATE OR REPLACE TABLE stg AS
SELECT DISTINCT ON (facility_id)
       lpad(trim(facility_id), 6, '0')                                   AS facility_id,
       upper(regexp_replace(trim(name), '\s+', ' ', 'g'))               AS name,
       upper(regexp_replace(trim(address), '\s+', ' ', 'g'))            AS address,
       upper(trim(city)) AS city, upper(trim(state)) AS state, left(trim(zip), 5) AS zip, upper(trim(county)) AS county,
       CASE WHEN trim(hospital_type) IN ('', 'Not Available') THEN 'Not Available' ELSE trim(hospital_type) END AS hospital_type,
       CASE WHEN trim(ownership) IN ('', 'Not Available') THEN 'Not Available' ELSE trim(ownership) END AS ownership,
       CASE upper(trim(emergency_services)) WHEN 'YES' THEN true WHEN 'NO' THEN false END AS emergency_services,
       TRY_CAST(overall_rating AS tinyint)                                AS overall_rating
  FROM read_csv('{file}', all_varchar = true, header = true)
 ORDER BY facility_id;
