"""
Strava Fitness Data Analytics — Streamlit app
---------------------------------------------
Run locally:   streamlit run streamlit_app.py
Data source:   database/strava_fitness.db  (built by scripts/build_database.py)
SQL analysis:  sql/02_analysis_queries.sql (every query runs live on the SQL page)
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database" / "strava_fitness.db"
QUERIES_PATH = ROOT / "sql" / "02_analysis_queries.sql"
CLEANING_PATH = ROOT / "sql" / "01_data_cleaning.sql"

st.set_page_config(page_title="Strava Fitness Analytics", page_icon=":material/directions_run:",
                   layout="wide")

# Colour-blind-safe palette, always used in this order
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
LIGHT_BLUE, GREY = "#86b6ef", "#9a9892"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------- data access
def connect() -> sqlite3.Connection:
    # read-only connection: the SQL page cannot change the database
    return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql(sql, conn, params=params)


@st.cache_data(show_spinner=False)
def load_named_queries() -> list[dict]:
    """Parse '-- [Qnn] Title' blocks from sql/02_analysis_queries.sql."""
    text = QUERIES_PATH.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=-- \[Q\d+\])", text)[1:]
    out = []
    for b in blocks:
        lines = b.strip().splitlines()
        title = re.sub(r"^-- \[(Q\d+)\]\s*", r"\1 · ", lines[0])
        question = lines[1].replace("-- Question:", "").strip() if len(lines) > 1 else ""
        body = "\n".join(lines[2:]).strip()
        body = body.split(";")[0].strip() + ";"
        out.append({"title": title, "question": question, "sql": body})
    return out


def style_fig(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=80 if legend else 50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, title=None),
        showlegend=legend, hoverlabel=dict(font_size=12),
        title=dict(font=dict(size=15), y=0.98, yanchor="top"),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridwidth=0.5)
    fig.update_traces(selector=dict(type="bar"), textangle=0, textposition="outside", cliponaxis=False)
    return fig


def show(fig: go.Figure):
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")


if not DB_PATH.exists():
    st.error("Database not found. Run `python scripts/build_database.py` first.")
    st.stop()


# ---------------------------------------------------------------- sidebar filters
users_all = q("SELECT * FROM user_profile")
date_bounds = q("SELECT MIN(activity_date) AS lo, MAX(activity_date) AS hi FROM daily_activity").iloc[0]


def sidebar_filters():
    st.sidebar.markdown("### Filters")
    levels = sorted(users_all.activity_level.unique())
    pick_levels = st.sidebar.multiselect(
        "Activity level", levels, default=levels, format_func=lambda s: s.split(". ")[1],
        help="Users grouped by their average daily steps")
    lo, hi = pd.to_datetime(date_bounds.lo).date(), pd.to_datetime(date_bounds.hi).date()
    rng = st.sidebar.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        rng = (lo, hi)
    ids = users_all.loc[users_all.activity_level.isin(pick_levels), "user_id"].tolist()
    st.sidebar.caption(f"{len(ids)} of {len(users_all)} users selected")
    return ids, str(rng[0]), str(rng[1])


def filtered(table: str, date_col: str, ids, d0, d1) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    marks = ",".join("?" * len(ids))
    return q(f"SELECT * FROM {table} WHERE user_id IN ({marks}) AND DATE({date_col}) BETWEEN ? AND ?",
             tuple(ids) + (d0, d1))


# ================================================================= PAGES
def page_overview():
    st.title("Strava Fitness Data Analytics")
    st.markdown(
        "**Business task:** understand how people use their fitness trackers, and turn those patterns "
        "into marketing recommendations for **Bellabeat**, a wellness-technology company for women.  \n"
        "Data: FitBit Fitness Tracker Data, 33 users, 12 Apr – 12 May 2016, cleaned in SQLite.")

    ids, d0, d1 = sidebar_filters()
    daily = filtered("daily_summary", "activity_date", ids, d0, d1)
    if daily.empty:
        st.warning("No data for the current filters."); return

    c = st.columns(5)
    c[0].metric("Users", daily.user_id.nunique())
    c[1].metric("Avg daily steps", f"{daily.total_steps.mean():,.0f}",
                f"{daily.total_steps.mean() - 10000:,.0f} vs 10k goal", delta_color="normal")
    c[2].metric("Days reaching 10k steps", f"{(daily.total_steps >= 10000).mean():.0%}")
    c[3].metric("Sedentary share of day", f"{daily.sedentary_min.sum() / daily.logged_min.sum():.0%}")
    c[4].metric("Avg sleep", f"{daily.hours_asleep.mean():.1f} h" if daily.hours_asleep.notna().any() else "–")

    left, right = st.columns([1.1, 1])
    with left:
        adopt = q("SELECT * FROM (" + load_named_queries()[1]["sql"].rstrip(";") + ")")
        adopt["label"] = adopt.apply(lambda r: f"{r.pct_of_users:.0f}% ({r.users} users)", axis=1)
        fig = px.bar(adopt.iloc[::-1], x="pct_of_users", y="feature", orientation="h", text="label",
                     color_discrete_sequence=[BLUE], title="Feature adoption: the more manual, the less used",
                     labels={"pct_of_users": "% of users", "feature": ""})
        fig.update_traces(textposition="outside", cliponaxis=False,
                          hovertemplate="%{y}: %{x:.0f}% of users<extra></extra>")
        fig.update_xaxes(range=[0, 140], ticksuffix="%", tickvals=[0, 25, 50, 75, 100])
        show(style_fig(fig, 320, legend=False))
    with right:
        tu = daily[["sedentary_min", "lightly_active_min", "fairly_active_min", "very_active_min"]].sum()
        tu = pd.DataFrame({"type": ["Sedentary", "Lightly active", "Fairly active", "Very active"],
                           "minutes": tu.values})
        fig = px.pie(tu, values="minutes", names="type", hole=0.62, title="How tracked time is spent",
                     color="type", color_discrete_map={"Sedentary": GREY, "Lightly active": BLUE,
                                                       "Fairly active": AQUA, "Very active": ORANGE})
        fig.update_traces(sort=False, textinfo="percent", marker=dict(line=dict(color="white", width=2)),
                          hovertemplate="%{label}: %{percent}<extra></extra>")
        show(style_fig(fig, 320))

    st.subheader("Key findings")
    k = st.columns(3)
    k[0].info("**Mostly sedentary.** About 79% of tracked time is sedentary, and only about a third of "
              "days reach 10,000 steps.")
    k[1].info("**Predictable rhythm.** Weekday activity peaks at 17:00–19:00; weekends peak at midday. "
              "Sunday is the least active day.")
    k[2].info("**Sleep gap.** Fewer than half of nights reach 7–9 hours. More sedentary days go with "
              "shorter sleep.")


def page_activity():
    st.title("Activity")
    ids, d0, d1 = sidebar_filters()
    daily = filtered("daily_activity", "activity_date", ids, d0, d1)
    hourly = filtered("hourly_activity", "activity_hour", ids, d0, d1)
    if daily.empty:
        st.warning("No data for the current filters."); return

    left, right = st.columns(2)
    with left:
        wd = daily.groupby("weekday", as_index=False).total_steps.mean()
        wd["weekday"] = pd.Categorical(wd.weekday, WEEKDAYS, ordered=True)
        wd = wd.sort_values("weekday")
        top2 = wd.nlargest(2, "total_steps").weekday.tolist()
        wd["colour"] = wd.weekday.apply(lambda d: "Top 2 days" if d in top2 else "Other days")
        fig = px.bar(wd, x="weekday", y="total_steps", color="colour", text_auto=",.0f",
                     color_discrete_map={"Top 2 days": BLUE, "Other days": LIGHT_BLUE},
                     title="Average steps by weekday", labels={"total_steps": "Avg steps", "weekday": ""},
                     category_orders={"weekday": WEEKDAYS})
        fig.add_hline(y=10000, line_dash="dash", line_color=ORANGE, annotation_text="10k goal",
                      annotation_position="bottom right")
        fig.update_traces(hovertemplate="%{x}: %{y:,.0f} steps<extra></extra>")
        show(style_fig(fig))
    with right:
        sb = daily.step_band.value_counts(normalize=True).sort_index().mul(100).reset_index()
        sb.columns = ["band", "pct"]
        sb["band"] = sb.band.str.split(". ", n=1, regex=False).str[1]
        fig = px.bar(sb, x="band", y="pct", text_auto=".0f", color_discrete_sequence=[BLUE],
                     title="Share of days by daily step count", labels={"pct": "% of days", "band": ""})
        fig.update_traces(texttemplate="%{y:.0f}%", hovertemplate="%{x}: %{y:.1f}% of days<extra></extra>")
        fig.update_yaxes(ticksuffix="%")
        show(style_fig(fig, legend=False))

    st.subheader("When are users active?")
    hourly["day_type"] = hourly.weekday_num.isin([0, 6]).map({True: "Weekend", False: "Weekday"})
    hp = hourly.groupby(["hour_of_day", "day_type"], as_index=False).steps.mean()
    fig = px.line(hp, x="hour_of_day", y="steps", color="day_type", markers=True,
                  color_discrete_map={"Weekday": BLUE, "Weekend": ORANGE},
                  title="Average steps per hour: weekday vs weekend",
                  labels={"hour_of_day": "Hour of day", "steps": "Avg steps", "day_type": ""})
    fig.update_traces(line_width=2, marker_size=6, hovertemplate="%{x}:00 → %{y:.0f} steps")
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(dtick=2, ticksuffix=":00")
    show(style_fig(fig, 380))

    heat = hourly.groupby(["weekday", "hour_of_day"]).steps.mean().unstack().reindex(WEEKDAYS)
    fig = px.imshow(heat, color_continuous_scale=SEQ_BLUE, aspect="auto",
                    labels=dict(x="Hour of day", y="", color="Avg steps"),
                    title="Activity heatmap: weekday × hour")
    fig.update_traces(hovertemplate="%{y} %{x}:00 → %{z:.0f} steps<extra></extra>", xgap=2, ygap=2)
    fig.update_xaxes(dtick=2)
    show(style_fig(fig, 340))

    left, right = st.columns(2)
    with left:
        act = daily.groupby("weekday")[["lightly_active_min", "fairly_active_min", "very_active_min"]].mean()
        act = act.reindex(WEEKDAYS).reset_index().melt("weekday", var_name="type", value_name="minutes")
        act["type"] = act.type.map({"lightly_active_min": "Lightly active", "fairly_active_min": "Fairly active",
                                    "very_active_min": "Very active"})
        fig = px.bar(act, x="weekday", y="minutes", color="type", barmode="stack",
                     color_discrete_map={"Lightly active": BLUE, "Fairly active": AQUA, "Very active": ORANGE},
                     title="Active minutes by intensity", labels={"weekday": "", "minutes": "Avg minutes"})
        fig.update_traces(marker_line_color="white", marker_line_width=1.5,
                          hovertemplate="%{x}: %{y:.0f} min<extra></extra>")
        show(style_fig(fig))
    with right:
        fig = px.scatter(daily, x="total_steps", y="calories", color="step_band", opacity=0.7,
                         color_discrete_sequence=[GREY, LIGHT_BLUE, BLUE, ORANGE],
                         category_orders={"step_band": sorted(daily.step_band.unique())},
                         title=f"Steps vs calories (r = {daily.total_steps.corr(daily.calories):.2f})",
                         labels={"total_steps": "Daily steps", "calories": "Calories", "step_band": ""},
                         hover_data={"user_id": True, "activity_date": True})
        fig.update_traces(marker=dict(size=8, line=dict(width=1, color="white")))
        show(style_fig(fig))


def page_sleep():
    st.title("Sleep")
    ids, d0, d1 = sidebar_filters()
    sleep = filtered("sleep_day", "sleep_date", ids, d0, d1)
    daily = filtered("daily_summary", "activity_date", ids, d0, d1)
    sess = filtered("sleep_sessions", "sleep_end", ids, d0, d1)
    if sleep.empty:
        st.warning("No sleep data for the current filters."); return

    c = st.columns(4)
    c[0].metric("Users tracking sleep", sleep.user_id.nunique())
    c[1].metric("Avg sleep", f"{sleep.hours_asleep.mean():.1f} h")
    c[2].metric("Nights with 7–9 h", f"{sleep.minutes_asleep.between(420, 540).mean():.0%}")
    c[3].metric("Avg awake in bed", f"{sleep.minutes_awake_in_bed.mean():.0f} min")

    left, right = st.columns(2)
    with left:
        fig = px.histogram(sleep, x="hours_asleep", nbins=24, color_discrete_sequence=[BLUE],
                           title="Hours asleep per night", labels={"hours_asleep": "Hours asleep"})
        fig.add_vrect(x0=7, x1=9, fillcolor=AQUA, opacity=0.12, line_width=0,
                      annotation_text="7–9 h recommended", annotation_position="top left")
        fig.update_traces(marker_line_color="white", marker_line_width=1.5,
                          hovertemplate="%{x} h: %{y} nights<extra></extra>")
        fig.update_yaxes(title="Nights")
        show(style_fig(fig, legend=False))
    with right:
        sleep["weekday"] = pd.Categorical(pd.to_datetime(sleep.sleep_date).dt.day_name(), WEEKDAYS, ordered=True)
        sw = sleep.groupby("weekday", observed=True, as_index=False).hours_asleep.mean()
        fig = px.bar(sw, x="weekday", y="hours_asleep", text_auto=".1f", color_discrete_sequence=[BLUE],
                     title="Average sleep by night", labels={"hours_asleep": "Hours", "weekday": ""})
        fig.add_hline(y=7, line_dash="dash", line_color=ORANGE, annotation_text="7 h",
                      annotation_position="bottom right")
        fig.update_traces(hovertemplate="%{x}: %{y:.2f} h<extra></extra>")
        show(style_fig(fig, legend=False))

    left, right = st.columns(2)
    with left:
        d = daily.dropna(subset=["hours_asleep"]).assign(sedentary_h=lambda x: x.sedentary_min / 60)
        r = d.sedentary_h.corr(d.hours_asleep)
        fig = px.scatter(d, x="sedentary_h", y="hours_asleep", trendline="ols",
                         color_discrete_sequence=[BLUE], trendline_color_override=ORANGE,
                         title=f"Sedentary hours vs sleep (r = {r:.2f})",
                         labels={"sedentary_h": "Sedentary hours", "hours_asleep": "Hours asleep"})
        fig.update_traces(marker=dict(size=8, opacity=0.6, line=dict(width=1, color="white")))
        show(style_fig(fig, legend=False))
        st.caption("Correlation, not causation. When the tracker is worn at night, time awake in bed can "
                   "count as sedentary, which strengthens this link.")
    with right:
        main = sess[sess.minutes_logged >= 180]
        order = list(range(18, 24)) + list(range(0, 6))
        bt = main.bedtime_hour.value_counts().reindex(order, fill_value=0).reset_index()
        bt.columns = ["hour", "logs"]
        bt["label"] = bt.hour.apply(lambda h: f"{h:02d}:00")
        bt["pct"] = bt.logs / max(bt.logs.sum(), 1) * 100
        fig = px.bar(bt, x="label", y="pct", color_discrete_sequence=[BLUE], title="Bedtime (main sleep)",
                     labels={"label": "Bedtime", "pct": "% of sleep logs"})
        fig.update_traces(hovertemplate="%{x}: %{y:.1f}%<extra></extra>")
        fig.update_yaxes(ticksuffix="%")
        show(style_fig(fig, legend=False))


def page_heart():
    st.title("Heart rate")
    st.caption("Only 14 of 33 users recorded heart rate. The 2.48 million readings were aggregated to hourly "
               "values in SQL.")
    ids, d0, d1 = sidebar_filters()
    hr = filtered("heart_rate_hourly", "hr_hour", ids, d0, d1)
    if hr.empty:
        st.warning("No heart-rate data for the current filters."); return

    c = st.columns(3)
    c[0].metric("Users with heart-rate data", hr.user_id.nunique())
    c[1].metric("Average BPM", f"{hr.avg_bpm.mean():.0f}")
    c[2].metric("Night-time avg (00–05h)", f"{hr[hr.hour_of_day < 6].avg_bpm.mean():.0f} BPM")

    hh = hr.groupby("hour_of_day", as_index=False).agg(avg_bpm=("avg_bpm", "mean"), max_bpm=("max_bpm", "max"))
    fig = px.line(hh, x="hour_of_day", y="avg_bpm", markers=True, color_discrete_sequence=[ORANGE],
                  title="Average heart rate by hour of day",
                  labels={"hour_of_day": "Hour of day", "avg_bpm": "Avg BPM"})
    fig.update_traces(line_width=2, marker_size=6, hovertemplate="%{x}:00 → %{y:.1f} BPM<extra></extra>")
    fig.update_xaxes(dtick=2, ticksuffix=":00")
    show(style_fig(fig, 360, legend=False))

    per_user = hr.groupby("user_id", as_index=False).agg(avg_bpm=("avg_bpm", "mean"), peak=("max_bpm", "max"))
    per_user["user"] = per_user.user_id.astype(str)
    per_user = per_user.sort_values("avg_bpm")
    fig = px.bar(per_user, x="avg_bpm", y="user", orientation="h", color_discrete_sequence=[BLUE],
                 text_auto=".0f", title="Average heart rate per user", labels={"avg_bpm": "Avg BPM", "user": ""},
                 hover_data={"peak": True})
    show(style_fig(fig, 420, legend=False))


def page_users():
    st.title("Users & engagement")
    ids, d0, d1 = sidebar_filters()
    users = users_all[users_all.user_id.isin(ids)]
    daily = filtered("daily_activity", "activity_date", ids, d0, d1)
    if users.empty:
        st.warning("No users for the current filters."); return

    left, right = st.columns(2)
    with left:
        seg = users.groupby("activity_level", as_index=False).agg(
            users=("user_id", "count"), avg_steps=("avg_steps", "mean"), days_worn=("days_worn", "mean"))
        seg["level"] = seg.activity_level.str.split(". ", n=1, regex=False).str[1]
        fig = px.bar(seg, x="level", y="users", text_auto=True, color_discrete_sequence=[BLUE],
                     title="Users by activity level", labels={"level": "", "users": "Users"},
                     hover_data={"avg_steps": ":,.0f", "days_worn": ":.1f"})
        show(style_fig(fig, legend=False))
    with right:
        wear = pd.cut(daily.logged_min, [0, 719, 1079, 1439, 1440],
                      labels=["Under 12h", "12–18h", "18–24h", "All day (24h)"])
        w = wear.value_counts(normalize=True).mul(100).reindex(["All day (24h)", "18–24h", "12–18h", "Under 12h"])
        w = w.reset_index(); w.columns = ["wear", "pct"]
        fig = px.bar(w, x="wear", y="pct", text_auto=".0f", color_discrete_sequence=[BLUE],
                     title="How long the tracker is worn each day", labels={"wear": "", "pct": "% of days"})
        fig.update_traces(texttemplate="%{y:.0f}%")
        fig.update_yaxes(ticksuffix="%")
        show(style_fig(fig, legend=False))

    daily["study_week"] = ((pd.to_datetime(daily.activity_date) - pd.Timestamp("2016-04-12")).dt.days // 7) + 1
    wk = daily.groupby("study_week", as_index=False).user_id.nunique()
    wk["week"] = wk.study_week.apply(lambda w: f"Week {w}" + (" (3 days)" if w == 5 else ""))
    fig = px.bar(wk, x="week", y="user_id", text_auto=True, color_discrete_sequence=[BLUE],
                 title="Users who wore the tracker, by study week", labels={"week": "", "user_id": "Users"})
    show(style_fig(fig, 320, legend=False))

    st.subheader("User profiles")
    view = users.copy()
    view["activity_level"] = view.activity_level.str.split(". ", n=1, regex=False).str[1]
    view["usage_level"] = view.usage_level.str.split(". ", n=1, regex=False).str[1]
    st.dataframe(
        view[["user_id", "activity_level", "usage_level", "days_worn", "avg_steps", "avg_calories",
              "avg_sedentary_min", "avg_very_active_min", "sleep_nights", "avg_sleep_hours", "hr_days",
              "weight_logs", "features_used"]],
        hide_index=True, use_container_width=True,
        column_config={"user_id": st.column_config.TextColumn("User"),
                       "avg_steps": st.column_config.ProgressColumn("Avg steps", format="%d", min_value=0,
                                                                    max_value=int(users_all.avg_steps.max()))})

    st.subheader("Single-user view")
    uid = st.selectbox("Choose a user", sorted(ids))
    ud = daily[daily.user_id == uid].sort_values("activity_date")
    fig = px.bar(ud, x="activity_date", y="total_steps", color_discrete_sequence=[BLUE],
                 title=f"Daily steps: user {uid}", labels={"activity_date": "", "total_steps": "Steps"})
    fig.add_hline(y=10000, line_dash="dash", line_color=ORANGE)
    show(style_fig(fig, 320, legend=False))


def page_sql():
    st.title("SQL analysis")
    st.markdown("Each query below is in `sql/02_analysis_queries.sql` and runs live against the cleaned "
                "SQLite database.")
    queries = load_named_queries()
    titles = [x["title"] for x in queries]
    pick = st.selectbox("Choose an analysis query", titles)
    item = queries[titles.index(pick)]
    st.markdown(f"**Business question:** {item['question']}")
    st.code(item["sql"], language="sql")
    res = q(item["sql"])
    st.dataframe(res, hide_index=True, use_container_width=True)

    # quick chart: first text column as x, first numeric column (excluding counts if possible) as y
    num_cols = [c for c in res.columns if pd.api.types.is_numeric_dtype(res[c]) and c not in ("user_id",)]
    x_col = res.columns[0]
    if len(res) > 1 and num_cols:
        y_col = st.selectbox("Chart column", num_cols, index=min(1, len(num_cols) - 1) if len(num_cols) > 1 else 0)
        fig = px.bar(res, x=res[x_col].astype(str), y=y_col, color_discrete_sequence=[BLUE],
                     labels={"x": x_col}, text_auto=True)
        show(style_fig(fig, 340, legend=False))

    st.divider()
    st.subheader("Write your own query")
    tables = q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").name.tolist()
    with st.expander("Tables and columns"):
        for t in tables:
            cols = q(f"PRAGMA table_info({t})").name.tolist()
            st.markdown(f"**{t}**: {', '.join(cols)}")
    custom = st.text_area("SQL (read-only, SELECT only)",
                          "SELECT weekday, ROUND(AVG(total_steps)) AS avg_steps\n"
                          "FROM daily_activity\nGROUP BY weekday\nORDER BY avg_steps DESC;", height=140)
    if st.button("Run query", type="primary"):
        if not re.match(r"^\s*(SELECT|WITH|PRAGMA)\b", custom, re.I):
            st.error("Only SELECT / WITH queries are allowed.")
        else:
            try:
                with connect() as conn:
                    st.dataframe(pd.read_sql(custom, conn), hide_index=True, use_container_width=True)
            except Exception as e:  # show SQL errors to the user
                st.error(f"SQL error: {e}")


def page_data():
    st.title("Data & cleaning")
    st.markdown("""
**Source:** [FitBit Fitness Tracker Data](https://www.kaggle.com/datasets/arashnic/fitbit) (Möbius, Kaggle, CC0).
Collected through an Amazon Mechanical Turk survey, 12 Apr – 12 May 2016. 33 users consented to share
minute-level activity, heart-rate and sleep data.

**Pipeline:** raw CSVs → `scripts/build_database.py` (load, convert timestamps to ISO) →
`sql/01_data_cleaning.sql` (all cleaning rules) → `database/strava_fitness.db` → this app.
""")
    st.subheader("Cleaning log")
    log = q("SELECT step_no AS step, table_name AS 'table', action, rows_before, rows_after, rows_removed "
            "FROM cleaning_log")
    st.dataframe(log, hide_index=True, use_container_width=True)

    st.subheader("Data limitations")
    st.markdown("""
- **Small sample:** 33 users (24 with sleep, 14 with heart rate, 8 with weight); results are directional.
- **No demographics:** no age or sex, and Bellabeat's customers are women.
- **Old and short:** one month of data from 2016.
- **Distance unit** is not documented, so it is used only for relative comparisons.
- **Wear time varies:** about half of days are not full 24-hour wear.
""")

    st.subheader("Browse and download clean tables")
    tables = q("SELECT name FROM sqlite_master WHERE type='table' AND name <> 'cleaning_log' ORDER BY name").name
    t = st.selectbox("Table", tables, index=list(tables).index("daily_summary"))
    df = q(f"SELECT * FROM {t}")
    st.caption(f"{len(df):,} rows × {df.shape[1]} columns")
    st.dataframe(df.head(500), hide_index=True, use_container_width=True)
    st.download_button("Download CSV", df.to_csv(index=False).encode(), f"{t}.csv", "text/csv")

    with st.expander("View the SQL cleaning script"):
        st.code(CLEANING_PATH.read_text(encoding="utf-8"), language="sql")


def page_recommendations():
    st.title("Recommendations for Bellabeat")
    st.markdown("""
Based on these usage patterns, here are six recommendations for the Bellabeat app and the **Leaf** tracker:

| # | Insight | Recommendation |
|---|---|---|
| 1 | 79% of tracked time is sedentary, and only ~35% of days hit 10k steps | **Move reminders:** nudge after 60 min without movement, and reframe goals as achievable steps (e.g. 7,500) that build towards 10k. |
| 2 | Weekday activity peaks at 17:00–19:00; weekends at midday | **Time the marketing:** send workout prompts, challenges and push campaigns just before these windows. |
| 3 | Sunday is the least active day; Tuesday and Saturday the most | **Sunday challenges:** weekend walking challenges and "reset" content to lift the lowest day. |
| 4 | <50% of nights reach 7–9 h, and sedentary days go with shorter sleep | **Sleep + activity bundle:** a bedtime reminder around 22:00 (most common bedtime) and a sleep score that links more movement with better rest. |
| 5 | Adoption falls from 100% (activity) to 24% (weight) as manual effort rises | **Reduce friction:** auto-sync a smart scale, one-tap logging, and highlight features that need no manual entry. |
| 6 | Half of days are not full 24-hour wear, and engagement fades after ~3 weeks | **Wearability & retention:** market Leaf as comfortable jewellery for 24/7 wear, and use streaks and badges to keep users engaged. |
""")
    st.info("**Next step:** validate these findings with Bellabeat's own (female) user data. It should be larger, "
            "more recent, and include age and life-stage details.")


# ================================================================= navigation
pages = [
    st.Page(page_overview, title="Overview", icon=":material/dashboard:", default=True),
    st.Page(page_activity, title="Activity", icon=":material/directions_walk:", url_path="activity"),
    st.Page(page_sleep, title="Sleep", icon=":material/bedtime:", url_path="sleep"),
    st.Page(page_heart, title="Heart rate", icon=":material/favorite:", url_path="heart-rate"),
    st.Page(page_users, title="Users & engagement", icon=":material/group:", url_path="users"),
    st.Page(page_sql, title="SQL analysis", icon=":material/database:", url_path="sql"),
    st.Page(page_data, title="Data & cleaning", icon=":material/cleaning_services:", url_path="data"),
    st.Page(page_recommendations, title="Recommendations", icon=":material/lightbulb:", url_path="recommendations"),
]
st.navigation(pages).run()
