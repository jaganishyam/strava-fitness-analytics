/* =====================================================================
   STRAVA FITNESS ANALYTICS  |  01_data_cleaning.sql
   ---------------------------------------------------------------------
   Runs after scripts/build_database.py has loaded the raw CSVs into
   raw_* staging tables (timestamps already converted to ISO format).
   Can also be run step-by-step in DB Browser for SQLite.

   Output tables
     daily_activity     one row per user per day the tracker was worn
     sleep_day          one row per user per night (duplicates removed)
     sleep_sessions     one row per sleep log, built from minute-level data
     weight_log         weight / BMI entries (empty Fat column dropped)
     hourly_activity    steps + calories + intensity per user per hour
     heart_rate_hourly  2.48M heart-rate readings summarised per hour
     heart_rate_daily   heart-rate summary per user per day
     daily_summary      activity + sleep + heart rate joined per user-day
     user_profile       one row per user: usage, activity level, segments
     cleaning_log       row counts before/after every cleaning step
   ===================================================================== */

DROP TABLE IF EXISTS cleaning_log;
CREATE TABLE cleaning_log (
    step_no     INTEGER,
    table_name  TEXT,
    action      TEXT,
    rows_before INTEGER,
    rows_after  INTEGER,
    rows_removed INTEGER
);


/* ---------------------------------------------------------------------
   STEP 1  Integrity checks on raw data (results recorded in cleaning_log)
   --------------------------------------------------------------------- */

-- 1a. Negative values in daily activity (expected: 0)
INSERT INTO cleaning_log
SELECT 1, 'raw_daily_activity', 'Check: rows with negative values (none expected)',
       COUNT(*), COUNT(*) - SUM(neg), SUM(neg)
FROM (
    SELECT CASE WHEN TotalSteps < 0 OR TotalDistance < 0 OR Calories < 0
                  OR VeryActiveMinutes < 0 OR FairlyActiveMinutes < 0
                  OR LightlyActiveMinutes < 0 OR SedentaryMinutes < 0
                THEN 1 ELSE 0 END AS neg
    FROM raw_daily_activity
);

-- 1b. NULLs in key columns (expected: 0)
INSERT INTO cleaning_log
SELECT 1, 'raw_daily_activity', 'Check: rows with NULL Id / date / steps / calories',
       COUNT(*), COUNT(*) - SUM(CASE WHEN Id IS NULL OR ActivityDate IS NULL
                                       OR TotalSteps IS NULL OR Calories IS NULL THEN 1 ELSE 0 END),
       SUM(CASE WHEN Id IS NULL OR ActivityDate IS NULL
                  OR TotalSteps IS NULL OR Calories IS NULL THEN 1 ELSE 0 END)
FROM raw_daily_activity;


/* ---------------------------------------------------------------------
   STEP 2  daily_activity
   Rule: remove "non-wear" days -> TotalSteps = 0.
         On these days the tracker logged ~1,440 sedentary minutes with
         no movement at all, i.e. the device was not worn.
   Added: weekday, total active minutes, logged (wear) minutes, step band
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS daily_activity;
CREATE TABLE daily_activity AS
SELECT
    Id                                   AS user_id,
    ActivityDate                         AS activity_date,
    CAST(strftime('%w', ActivityDate) AS INTEGER) AS weekday_num,   -- 0 = Sunday
    CASE strftime('%w', ActivityDate)
        WHEN '0' THEN 'Sunday'   WHEN '1' THEN 'Monday'  WHEN '2' THEN 'Tuesday'
        WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday'
        ELSE 'Saturday' END              AS weekday,
    CASE WHEN strftime('%w', ActivityDate) IN ('0','6') THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    TotalSteps                           AS total_steps,
    ROUND(TotalDistance, 2)              AS total_distance,
    VeryActiveMinutes                    AS very_active_min,
    FairlyActiveMinutes                  AS fairly_active_min,
    LightlyActiveMinutes                 AS lightly_active_min,
    SedentaryMinutes                     AS sedentary_min,
    VeryActiveMinutes + FairlyActiveMinutes + LightlyActiveMinutes            AS total_active_min,
    VeryActiveMinutes + FairlyActiveMinutes                                   AS moderate_vigorous_min,
    VeryActiveMinutes + FairlyActiveMinutes + LightlyActiveMinutes + SedentaryMinutes AS logged_min,
    Calories                             AS calories,
    CASE WHEN TotalSteps < 5000  THEN '1. Sedentary (<5k)'
         WHEN TotalSteps < 7500  THEN '2. Low active (5k-7.5k)'
         WHEN TotalSteps < 10000 THEN '3. Somewhat active (7.5k-10k)'
         ELSE '4. Active (10k+)' END     AS step_band
FROM raw_daily_activity
WHERE TotalSteps > 0;

INSERT INTO cleaning_log
SELECT 2, 'daily_activity', 'Removed non-wear days (TotalSteps = 0)',
       (SELECT COUNT(*) FROM raw_daily_activity),
       (SELECT COUNT(*) FROM daily_activity),
       (SELECT COUNT(*) FROM raw_daily_activity) - (SELECT COUNT(*) FROM daily_activity);


/* ---------------------------------------------------------------------
   STEP 3  sleep_day
   Rule: remove exact duplicate rows (3 found).
   Added: hours asleep, minutes awake in bed, sleep efficiency %
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS sleep_day;
CREATE TABLE sleep_day AS
SELECT DISTINCT
    Id                                   AS user_id,
    SleepDay                             AS sleep_date,
    TotalSleepRecords                    AS sleep_records,
    TotalMinutesAsleep                   AS minutes_asleep,
    TotalTimeInBed                       AS minutes_in_bed,
    ROUND(TotalMinutesAsleep / 60.0, 2)  AS hours_asleep,
    TotalTimeInBed - TotalMinutesAsleep  AS minutes_awake_in_bed,
    ROUND(100.0 * TotalMinutesAsleep / TotalTimeInBed, 1) AS sleep_efficiency_pct,
    CASE WHEN TotalMinutesAsleep < 360 THEN '1. Under 6h'
         WHEN TotalMinutesAsleep < 420 THEN '2. 6-7h'
         WHEN TotalMinutesAsleep <= 540 THEN '3. 7-9h (recommended)'
         ELSE '4. Over 9h' END           AS sleep_band
FROM raw_sleep_day;

INSERT INTO cleaning_log
SELECT 3, 'sleep_day', 'Removed exact duplicate rows',
       (SELECT COUNT(*) FROM raw_sleep_day),
       (SELECT COUNT(*) FROM sleep_day),
       (SELECT COUNT(*) FROM raw_sleep_day) - (SELECT COUNT(*) FROM sleep_day);


/* ---------------------------------------------------------------------
   STEP 4  sleep_sessions  (from minuteSleep: 1 = asleep, 2 = restless, 3 = awake)
   Rule: remove duplicate minute rows, then summarise per sleep log.
   Gives bedtime / wake-up time, which the daily file does not have.
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS sleep_sessions;
CREATE TABLE sleep_sessions AS
WITH dedup AS (
    SELECT DISTINCT Id, date, value, logId FROM raw_minute_sleep
)
SELECT
    Id                                   AS user_id,
    logId                                AS log_id,
    MIN(date)                            AS sleep_start,
    MAX(date)                            AS sleep_end,
    CAST(strftime('%H', MIN(date)) AS INTEGER) AS bedtime_hour,
    CAST(strftime('%H', MAX(date)) AS INTEGER) AS wake_hour,
    DATE(MAX(date))                      AS wake_date,
    SUM(value = 1)                       AS minutes_asleep,
    SUM(value = 2)                       AS minutes_restless,
    SUM(value = 3)                       AS minutes_awake,
    COUNT(*)                             AS minutes_logged
FROM dedup
GROUP BY Id, logId;

INSERT INTO cleaning_log
SELECT 4, 'sleep_sessions', 'Removed duplicate minute-sleep rows, then grouped per sleep log',
       (SELECT COUNT(*) FROM raw_minute_sleep),
       (SELECT COUNT(*) FROM (SELECT DISTINCT Id, date, value, logId FROM raw_minute_sleep)),
       (SELECT COUNT(*) FROM raw_minute_sleep)
         - (SELECT COUNT(*) FROM (SELECT DISTINCT Id, date, value, logId FROM raw_minute_sleep));


/* ---------------------------------------------------------------------
   STEP 5  weight_log
   Rule: drop 'Fat' (65 of 67 values empty) and 'WeightPounds' (duplicate
         of WeightKg). Convert IsManualReport text to 0/1.
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS weight_log;
CREATE TABLE weight_log AS
SELECT
    Id                                   AS user_id,
    DATE(Date)                           AS log_date,
    ROUND(WeightKg, 1)                   AS weight_kg,
    ROUND(BMI, 1)                        AS bmi,
    CASE WHEN IsManualReport IN ('True', 1) THEN 1 ELSE 0 END AS is_manual,
    CASE WHEN BMI < 18.5 THEN 'Underweight'
         WHEN BMI < 25   THEN 'Healthy'
         WHEN BMI < 30   THEN 'Overweight'
         ELSE 'Obese' END                AS bmi_category
FROM raw_weight_log;

INSERT INTO cleaning_log
SELECT 5, 'weight_log', 'Dropped Fat (97% empty) and WeightPounds (duplicate) columns',
       (SELECT COUNT(*) FROM raw_weight_log), (SELECT COUNT(*) FROM weight_log), 0;


/* ---------------------------------------------------------------------
   STEP 6  hourly_activity
   Rule: join the three hourly files into one table (same Id + hour key).
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS hourly_activity;
CREATE TABLE hourly_activity AS
SELECT
    s.Id                                 AS user_id,
    s.ActivityHour                       AS activity_hour,
    DATE(s.ActivityHour)                 AS activity_date,
    CAST(strftime('%H', s.ActivityHour) AS INTEGER) AS hour_of_day,
    CAST(strftime('%w', s.ActivityHour) AS INTEGER) AS weekday_num,
    CASE strftime('%w', s.ActivityHour)
        WHEN '0' THEN 'Sunday'   WHEN '1' THEN 'Monday'  WHEN '2' THEN 'Tuesday'
        WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday'
        ELSE 'Saturday' END              AS weekday,
    s.StepTotal                          AS steps,
    c.Calories                           AS calories,
    i.TotalIntensity                     AS total_intensity,
    ROUND(i.AverageIntensity, 3)         AS avg_intensity
FROM raw_hourly_steps s
JOIN raw_hourly_calories    c ON c.Id = s.Id AND c.ActivityHour = s.ActivityHour
JOIN raw_hourly_intensities i ON i.Id = s.Id AND i.ActivityHour = s.ActivityHour;

INSERT INTO cleaning_log
SELECT 6, 'hourly_activity', 'Joined hourly steps + calories + intensities on Id and hour',
       (SELECT COUNT(*) FROM raw_hourly_steps), (SELECT COUNT(*) FROM hourly_activity),
       (SELECT COUNT(*) FROM raw_hourly_steps) - (SELECT COUNT(*) FROM hourly_activity);


/* ---------------------------------------------------------------------
   STEP 7  heart_rate_hourly / heart_rate_daily
   Rule: 2,483,658 readings (every 5-15 s) are too granular for a
         dashboard, so aggregate them. Raw table is dropped afterwards.
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS heart_rate_hourly;
CREATE TABLE heart_rate_hourly AS
SELECT
    Id                                   AS user_id,
    substr(Time, 1, 13) || ':00:00'      AS hr_hour,
    DATE(Time)                           AS hr_date,
    CAST(strftime('%H', Time) AS INTEGER) AS hour_of_day,
    ROUND(AVG(Value), 1)                 AS avg_bpm,
    MIN(Value)                           AS min_bpm,
    MAX(Value)                           AS max_bpm,
    COUNT(*)                             AS readings
FROM raw_heartrate_seconds
GROUP BY Id, substr(Time, 1, 13);

DROP TABLE IF EXISTS heart_rate_daily;
CREATE TABLE heart_rate_daily AS
SELECT
    Id                                   AS user_id,
    DATE(Time)                           AS hr_date,
    ROUND(AVG(Value), 1)                 AS avg_bpm,
    MIN(Value)                           AS min_bpm,
    MAX(Value)                           AS max_bpm,
    COUNT(*)                             AS readings
FROM raw_heartrate_seconds
GROUP BY Id, DATE(Time);

INSERT INTO cleaning_log
SELECT 7, 'heart_rate_hourly', 'Aggregated second-level heart rate to user-hour',
       (SELECT COUNT(*) FROM raw_heartrate_seconds), (SELECT COUNT(*) FROM heart_rate_hourly), NULL;


/* ---------------------------------------------------------------------
   STEP 8  daily_summary  (master table for dashboards)
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS daily_summary;
CREATE TABLE daily_summary AS
SELECT
    a.*,
    s.minutes_asleep,
    s.minutes_in_bed,
    s.hours_asleep,
    s.sleep_efficiency_pct,
    h.avg_bpm,
    h.min_bpm,
    h.max_bpm
FROM daily_activity a
LEFT JOIN sleep_day        s ON s.user_id = a.user_id AND s.sleep_date = a.activity_date
LEFT JOIN heart_rate_daily h ON h.user_id = a.user_id AND h.hr_date    = a.activity_date;


/* ---------------------------------------------------------------------
   STEP 9  user_profile  (one row per user - segmentation)
   Activity level uses Tudor-Locke step bands; usage level uses the
   number of days the tracker was actually worn (out of 31).
   --------------------------------------------------------------------- */
DROP TABLE IF EXISTS user_profile;
CREATE TABLE user_profile AS
WITH act AS (
    SELECT user_id,
           COUNT(*)                          AS days_worn,
           ROUND(AVG(total_steps))           AS avg_steps,
           ROUND(AVG(calories))              AS avg_calories,
           ROUND(AVG(sedentary_min))         AS avg_sedentary_min,
           ROUND(AVG(total_active_min))      AS avg_active_min,
           ROUND(AVG(very_active_min), 1)    AS avg_very_active_min,
           ROUND(AVG(logged_min))            AS avg_logged_min,
           ROUND(AVG(total_distance), 2)  AS avg_distance
    FROM daily_activity GROUP BY user_id
),
slp AS (
    SELECT user_id, COUNT(*) AS sleep_nights, ROUND(AVG(hours_asleep), 2) AS avg_sleep_hours
    FROM sleep_day GROUP BY user_id
),
hr AS (
    SELECT user_id, COUNT(*) AS hr_days, ROUND(AVG(avg_bpm), 1) AS avg_bpm
    FROM heart_rate_daily GROUP BY user_id
),
wt AS (
    SELECT user_id, COUNT(*) AS weight_logs, ROUND(AVG(bmi), 1) AS avg_bmi
    FROM weight_log GROUP BY user_id
)
SELECT
    act.*,
    COALESCE(slp.sleep_nights, 0)            AS sleep_nights,
    slp.avg_sleep_hours,
    COALESCE(hr.hr_days, 0)                  AS hr_days,
    hr.avg_bpm,
    COALESCE(wt.weight_logs, 0)              AS weight_logs,
    wt.avg_bmi,
    CASE WHEN act.avg_steps < 5000  THEN '1. Sedentary'
         WHEN act.avg_steps < 7500  THEN '2. Low active'
         WHEN act.avg_steps < 10000 THEN '3. Somewhat active'
         ELSE '4. Active' END                AS activity_level,
    CASE WHEN act.days_worn >= 21 THEN '3. High use (21-31 days)'
         WHEN act.days_worn >= 11 THEN '2. Moderate use (11-20 days)'
         ELSE '1. Low use (1-10 days)' END   AS usage_level,
    (CASE WHEN slp.sleep_nights IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN hr.hr_days       IS NOT NULL THEN 1 ELSE 0 END
   + CASE WHEN wt.weight_logs   IS NOT NULL THEN 1 ELSE 0 END) + 1 AS features_used
FROM act
LEFT JOIN slp ON slp.user_id = act.user_id
LEFT JOIN hr  ON hr.user_id  = act.user_id
LEFT JOIN wt  ON wt.user_id  = act.user_id;


/* ---------------------------------------------------------------------
   STEP 10  Indexes for fast dashboard queries
   --------------------------------------------------------------------- */
CREATE INDEX idx_daily_user   ON daily_activity(user_id, activity_date);
CREATE INDEX idx_hourly_user  ON hourly_activity(user_id, activity_hour);
CREATE INDEX idx_sleep_user   ON sleep_day(user_id, sleep_date);
CREATE INDEX idx_hr_hour_user ON heart_rate_hourly(user_id, hr_hour);
