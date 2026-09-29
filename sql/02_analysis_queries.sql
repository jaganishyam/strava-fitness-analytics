/* =====================================================================
   STRAVA FITNESS ANALYTICS  |  02_analysis_queries.sql
   ---------------------------------------------------------------------
   Business task: how are consumers using their smart devices, and what
   does that mean for Bellabeat's marketing strategy?

   Each query starts with a "-- [Qnn] Title" line and a "-- Question:"
   line. The Streamlit app reads this file and lets you run every query
   from the "SQL Analysis" page, so keep that header format.
   ===================================================================== */


-- [Q01] Dataset overview
-- Question: How much clean data do we have after cleaning?
SELECT
    COUNT(DISTINCT user_id)                    AS users,
    COUNT(*)                                   AS user_days,
    MIN(activity_date)                         AS first_day,
    MAX(activity_date)                         AS last_day,
    ROUND(AVG(total_steps))                    AS avg_daily_steps,
    ROUND(AVG(calories))                       AS avg_daily_calories,
    ROUND(AVG(sedentary_min) / 60.0, 1)        AS avg_sedentary_hours,
    ROUND(AVG(total_active_min))               AS avg_active_min
FROM daily_activity;


-- [Q02] Feature adoption
-- Question: Which tracker features do users actually use?
SELECT 'Activity tracking' AS feature, COUNT(DISTINCT user_id) AS users,
       ROUND(100.0 * COUNT(DISTINCT user_id) / 33, 1) AS pct_of_users FROM daily_activity
UNION ALL
SELECT 'Sleep tracking',  COUNT(DISTINCT user_id), ROUND(100.0 * COUNT(DISTINCT user_id) / 33, 1) FROM sleep_day
UNION ALL
SELECT 'Heart-rate monitoring', COUNT(DISTINCT user_id), ROUND(100.0 * COUNT(DISTINCT user_id) / 33, 1) FROM heart_rate_daily
UNION ALL
SELECT 'Weight logging',  COUNT(DISTINCT user_id), ROUND(100.0 * COUNT(DISTINCT user_id) / 33, 1) FROM weight_log
ORDER BY users DESC;


-- [Q03] Average steps by weekday
-- Question: Which days are users most and least active?
SELECT
    weekday,
    COUNT(*)                                   AS user_days,
    ROUND(AVG(total_steps))                    AS avg_steps,
    ROUND(AVG(total_active_min))               AS avg_active_min,
    ROUND(AVG(sedentary_min))                  AS avg_sedentary_min,
    ROUND(AVG(calories))                       AS avg_calories
FROM daily_activity
GROUP BY weekday_num, weekday
ORDER BY weekday_num;


-- [Q04] Share of days hitting 10,000 steps
-- Question: How often do users reach the popular 10k-steps goal?
SELECT
    step_band,
    COUNT(*)                                   AS user_days,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM daily_activity), 1) AS pct_of_days
FROM daily_activity
GROUP BY step_band
ORDER BY step_band;


-- [Q05] How the day is spent
-- Question: What share of logged time is sedentary vs active?
SELECT
    ROUND(100.0 * SUM(sedentary_min)      / SUM(logged_min), 1) AS pct_sedentary,
    ROUND(100.0 * SUM(lightly_active_min) / SUM(logged_min), 1) AS pct_lightly_active,
    ROUND(100.0 * SUM(fairly_active_min)  / SUM(logged_min), 1) AS pct_fairly_active,
    ROUND(100.0 * SUM(very_active_min)    / SUM(logged_min), 1) AS pct_very_active
FROM daily_activity;


-- [Q06] WHO 150-minute guideline
-- Question: How many users average 150+ minutes of moderate/vigorous activity per week?
WITH weekly AS (
    SELECT user_id, AVG(moderate_vigorous_min) * 7 AS weekly_mvpa_min
    FROM daily_activity GROUP BY user_id
)
SELECT
    CASE WHEN weekly_mvpa_min >= 150 THEN 'Meets 150 min/week' ELSE 'Below 150 min/week' END AS who_guideline,
    COUNT(*)                                   AS users,
    ROUND(AVG(weekly_mvpa_min))                AS avg_weekly_mvpa_min
FROM weekly
GROUP BY 1;


-- [Q07] Busiest hours of the day
-- Question: At what time of day are users most active?
SELECT
    hour_of_day,
    ROUND(AVG(steps))                          AS avg_steps,
    ROUND(AVG(calories))                       AS avg_calories,
    ROUND(AVG(total_intensity), 1)             AS avg_intensity
FROM hourly_activity
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- [Q08] Weekday vs weekend hourly pattern
-- Question: Does the daily rhythm change at the weekend?
SELECT
    hour_of_day,
    ROUND(AVG(CASE WHEN weekday_num BETWEEN 1 AND 5 THEN steps END)) AS weekday_avg_steps,
    ROUND(AVG(CASE WHEN weekday_num IN (0, 6)      THEN steps END)) AS weekend_avg_steps
FROM hourly_activity
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- [Q09] Sleep duration distribution
-- Question: How many nights meet the recommended 7-9 hours?
SELECT
    sleep_band,
    COUNT(*)                                   AS nights,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sleep_day), 1) AS pct_of_nights,
    ROUND(AVG(sleep_efficiency_pct), 1)        AS avg_efficiency_pct
FROM sleep_day
GROUP BY sleep_band
ORDER BY sleep_band;


-- [Q10] Sleep by weekday
-- Question: Which nights do users sleep the most and least?
SELECT
    CASE strftime('%w', sleep_date)
        WHEN '0' THEN 'Sunday'   WHEN '1' THEN 'Monday'  WHEN '2' THEN 'Tuesday'
        WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday'
        ELSE 'Saturday' END                    AS weekday,
    COUNT(*)                                   AS nights,
    ROUND(AVG(hours_asleep), 2)                AS avg_hours_asleep,
    ROUND(AVG(minutes_awake_in_bed))           AS avg_min_awake_in_bed
FROM sleep_day
GROUP BY strftime('%w', sleep_date)
ORDER BY strftime('%w', sleep_date);


-- [Q11] Sedentary time vs sleep
-- Question: Do users with more sedentary time sleep less?
SELECT
    CASE WHEN sedentary_min < 600 THEN '1. < 10h sedentary'
         WHEN sedentary_min < 780 THEN '2. 10-13h sedentary'
         ELSE '3. 13h+ sedentary' END          AS sedentary_band,
    COUNT(*)                                   AS nights,
    ROUND(AVG(hours_asleep), 2)                AS avg_hours_asleep
FROM daily_summary
WHERE hours_asleep IS NOT NULL
GROUP BY 1
ORDER BY 1;


-- [Q12] Steps vs calories
-- Question: Do more active days burn more calories?
SELECT
    step_band,
    COUNT(*)                                   AS user_days,
    ROUND(AVG(calories))                       AS avg_calories,
    ROUND(AVG(very_active_min), 1)             AS avg_very_active_min
FROM daily_activity
GROUP BY step_band
ORDER BY step_band;


-- [Q13] User segments
-- Question: How are users split by activity level and by how often they wear the tracker?
SELECT
    activity_level,
    COUNT(*)                                   AS users,
    ROUND(AVG(avg_steps))                      AS avg_steps,
    ROUND(AVG(days_worn), 1)                   AS avg_days_worn,
    ROUND(AVG(avg_sedentary_min) / 60.0, 1)    AS avg_sedentary_hours,
    ROUND(AVG(avg_calories))                   AS avg_calories
FROM user_profile
GROUP BY activity_level
ORDER BY activity_level;


-- [Q14] Tracker wear time
-- Question: Do users wear the tracker all day, including at night?
SELECT
    CASE WHEN logged_min >= 1440 THEN '1. All day (24h)'
         WHEN logged_min >= 1080 THEN '2. Most of day (18-24h)'
         WHEN logged_min >= 720  THEN '3. Half day (12-18h)'
         ELSE '4. Under 12h' END               AS wear_time,
    COUNT(*)                                   AS user_days,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM daily_activity), 1) AS pct_of_days,
    ROUND(AVG(total_steps))                    AS avg_steps
FROM daily_activity
GROUP BY 1
ORDER BY 1;


-- [Q15] Engagement drop-off over the month
-- Question: Do users stop wearing the tracker as the month goes on?
SELECT
    CAST((julianday(activity_date) - julianday('2016-04-12')) / 7 AS INTEGER) + 1 AS study_week,
    COUNT(DISTINCT user_id)                    AS active_users,
    COUNT(*)                                   AS user_days,
    ROUND(AVG(total_steps))                    AS avg_steps
FROM daily_activity
GROUP BY study_week
ORDER BY study_week;


-- [Q16] Heart rate by hour of day
-- Question: When is heart rate highest (14 users with heart-rate data)?
SELECT
    hour_of_day,
    ROUND(AVG(avg_bpm), 1)                     AS avg_bpm,
    MAX(max_bpm)                               AS peak_bpm
FROM heart_rate_hourly
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- [Q17] Typical bedtime
-- Question: What time do users usually go to sleep?
SELECT
    bedtime_hour,
    COUNT(*)                                   AS sleep_logs,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sleep_sessions WHERE minutes_logged >= 180), 1) AS pct_of_logs
FROM sleep_sessions
WHERE minutes_logged >= 180          -- main sleep only, ignore short naps
GROUP BY bedtime_hour
ORDER BY CASE WHEN bedtime_hour < 12 THEN bedtime_hour + 24 ELSE bedtime_hour END;


-- [Q18] Top 10 most active users
-- Question: Who are the most active users, and do they use more features?
SELECT
    user_id,
    avg_steps,
    days_worn,
    avg_very_active_min,
    avg_sleep_hours,
    features_used
FROM user_profile
ORDER BY avg_steps DESC
LIMIT 10;
