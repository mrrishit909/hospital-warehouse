-- Load one CMS release ({snap}) after 02_stage.sql has filled stg. Each step writes its row count to audit_step.
CREATE OR REPLACE TEMP TABLE audit_step (step varchar, n integer);

-- Type 1: overwrite descriptive attributes on every version of each hospital in this release.
INSERT INTO audit_step SELECT 'type1', count(DISTINCT d.facility_id) FROM dim_hospital d JOIN stg s USING (facility_id)
 WHERE d.name IS DISTINCT FROM s.name OR d.address IS DISTINCT FROM s.address OR d.city IS DISTINCT FROM s.city
    OR d.zip IS DISTINCT FROM s.zip OR d.county IS DISTINCT FROM s.county;
UPDATE dim_hospital d SET name = s.name, address = s.address, city = s.city, state = s.state, zip = s.zip, county = s.county
  FROM stg s WHERE d.facility_id = s.facility_id;

-- Type 2: a tracked attribute changed -> close the current version and open a new one.
CREATE OR REPLACE TEMP TABLE changed AS
SELECT d.hospital_sk, d.hospital_key, s.*,
       CASE WHEN d.ownership <> s.ownership THEN 'ownership' WHEN d.hospital_type <> s.hospital_type THEN 'type' ELSE 'emergency' END AS reason
  FROM dim_hospital d JOIN stg s USING (facility_id)
 WHERE d.is_current AND (d.ownership <> s.ownership OR d.hospital_type <> s.hospital_type
                         OR d.emergency_services IS DISTINCT FROM s.emergency_services);
INSERT INTO audit_step SELECT 'new_versions', count(*) FROM changed;
UPDATE dim_hospital SET valid_to = DATE '{snap}', is_current = false WHERE hospital_sk IN (SELECT hospital_sk FROM changed);
INSERT INTO dim_hospital (hospital_key, facility_id, name, address, city, state, zip, county, hospital_type, ownership,
                          emergency_services, valid_from, valid_to, is_current, change_reason)
SELECT hospital_key, facility_id, name, address, city, state, zip, county, hospital_type, ownership, emergency_services,
       DATE '{snap}', NULL, true, reason FROM changed;

-- Left the data: close the current version (it may come back later as a new version).
CREATE OR REPLACE TEMP TABLE closed AS
SELECT hospital_sk FROM dim_hospital WHERE is_current AND facility_id NOT IN (SELECT facility_id FROM stg);
INSERT INTO audit_step SELECT 'closed', count(*) FROM closed;
UPDATE dim_hospital SET valid_to = DATE '{snap}', is_current = false WHERE hospital_sk IN (SELECT hospital_sk FROM closed);

-- Came back after being absent: a new version with the same durable key.
CREATE OR REPLACE TEMP TABLE returned AS
SELECT s.*, (SELECT max(hospital_key) FROM dim_hospital d WHERE d.facility_id = s.facility_id) AS hospital_key
  FROM stg s WHERE s.facility_id IN (SELECT facility_id FROM dim_hospital)
   AND s.facility_id NOT IN (SELECT facility_id FROM dim_hospital WHERE is_current);
INSERT INTO audit_step SELECT 'reopened', count(*) FROM returned;
INSERT INTO dim_hospital (hospital_key, facility_id, name, address, city, state, zip, county, hospital_type, ownership,
                          emergency_services, valid_from, valid_to, is_current, change_reason)
SELECT hospital_key, facility_id, name, address, city, state, zip, county, hospital_type, ownership, emergency_services,
       DATE '{snap}', NULL, true, 'returned' FROM returned;

-- Never seen: a new hospital, or a known hospital under a new facility ID (via hospital_lineage).
CREATE OR REPLACE TEMP TABLE brand_new AS
SELECT s.*, (SELECT max(d.hospital_key) FROM hospital_lineage l JOIN dim_hospital d ON d.facility_id = l.old_facility_id
              WHERE l.new_facility_id = s.facility_id) AS inherited_key
  FROM stg s WHERE s.facility_id NOT IN (SELECT facility_id FROM dim_hospital);
INSERT INTO audit_step SELECT 'new_hospitals', count(*) FROM brand_new;
INSERT INTO dim_hospital (hospital_key, facility_id, name, address, city, state, zip, county, hospital_type, ownership,
                          emergency_services, valid_from, valid_to, is_current, change_reason)
SELECT coalesce(inherited_key, nextval('hospital_key_seq')), facility_id, name, address, city, state, zip, county, hospital_type,
       ownership, emergency_services, DATE '{snap}', NULL, true,
       CASE WHEN inherited_key IS NULL THEN 'first seen' ELSE 'new facility ID' END FROM brand_new;

-- The periodic snapshot fact: this release's rating, attached to the version current on this date.
INSERT INTO fact_rating
SELECT DATE '{snap}', d.hospital_sk, d.hospital_key, s.overall_rating
  FROM stg s JOIN dim_hospital d ON d.facility_id = s.facility_id AND d.is_current;
INSERT INTO audit_step SELECT 'facts', count(*) FROM fact_rating WHERE date_key = DATE '{snap}';
