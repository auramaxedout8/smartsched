import sqlite3
from datetime import datetime, time
import pandas as pd
import streamlit as st

# --- DATABASE SETUP ---
DB_NAME = "student_sched.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            subject TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            priority TEXT NOT NULL,
            duration_mins INTEGER NOT NULL,
            deadline TEXT NOT NULL,
            completed INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    data = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data

# --- TIME HELPER FUNCTIONS ---
def to_minutes(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def to_time_str(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

# --- AUTO-SCHEDULER ALGORITHM ---
def generate_daily_schedule(day, wake_mins, sleep_mins, break_mins=10):
    # 1. Fetch fixed classes for the selected day
    classes = run_query(
        "SELECT subject, start_time, end_time FROM classes WHERE day = ? ORDER BY start_time",
        (day,),
        fetch=True,
    )
    
    # Build timeline blocks: (start_min, end_min, activity, category)
    timeline = []
    for subj, start_t, end_t in classes:
        s_m, e_m = to_minutes(start_t), to_minutes(end_t)
        if s_m >= wake_mins and e_m <= sleep_mins:
            timeline.append((s_m, e_m, f"Class: {subj}", "Fixed Class"))
    
    timeline.sort(key=lambda x: x[0])

    # 2. Identify free time gaps
    free_gaps = []
    current = wake_mins
    for s_m, e_m, _, _ in timeline:
        if s_m > current:
            free_gaps.append([current, s_m])
        current = max(current, e_m)
    if current < sleep_mins:
        free_gaps.append([current, sleep_mins])

    # 3. Fetch pending tasks sorted by Priority (High -> Medium -> Low) & Deadline
    priority_order = {"High": 1, "Medium": 2, "Low": 3}
    tasks = run_query(
        "SELECT title, priority, duration_mins, deadline FROM tasks WHERE completed = 0",
        fetch=True,
    )
    tasks.sort(key=lambda x: (priority_order.get(x[1], 3), x[3]))

    # 4. Fit tasks into free gaps with breaks
    scheduled_tasks = []
    unscheduled_tasks = []

    for title, prio, dur, deadline in tasks:
        placed = False
        for gap in free_gaps:
            gap_start, gap_end = gap
            if (gap_end - gap_start) >= dur:
                task_end = gap_start + dur
                scheduled_tasks.append((gap_start, task_end, f"{title} ({prio})", "Study / Task"))
                
                # Add a short break if space remains
                if (gap_end - task_end) >= break_mins:
                    scheduled_tasks.append((task_end, task_end + break_mins, "Short Break", "Break"))
                    gap[0] = task_end + break_mins
                else:
                    gap[0] = task_end
                placed = True
                break
        if not placed:
            unscheduled_tasks.append(f"{title} ({dur} mins)")

    # 5. Merge and sort the complete daily schedule
    full_schedule = sorted(timeline + scheduled_tasks, key=lambda x: x[0])
    
    formatted = [
        {
            "Start": to_time_str(s),
            "End": to_time_str(e),
            "Duration (mins)": e - s,
            "Activity": act,
            "Type": cat,
        }
        for s, e, act, cat in full_schedule
    ]
    return pd.DataFrame(formatted), unscheduled_tasks

# --- STREAMLIT UI ---
st.set_page_config(page_title="SmartSched - Student Time Manager", layout="wide")
init_db()

st.title("SmartSched: College Student Time Manager")
st.caption("Organize your fixed college timetable and auto-schedule your study tasks.")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
tab1, tab2, tab3 = st.tabs(["1. Fixed Classes", "2. Tasks & Assignments", "3. Auto-Generated Schedule"])

# --- TAB 1: FIXED CLASSES ---
with tab1:
    st.subheader("Add Your College Classes / Labs")
    with st.form("class_form", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        day = col1.selectbox("Day", DAYS)
        subject = col2.text_input("Subject / Lab Name", placeholder="e.g., Data Structures")
        start_t = col3.time_input("Start Time", value=time(9, 0))
        end_t = col4.time_input("End Time", value=time(10, 0))
        submitted = st.form_submit_button("Add Class")

        if submitted:
            if not subject.strip():
                st.error("Please enter a subject name.")
            elif start_t >= end_t:
                st.error("End time must be after start time.")
            else:
                run_query(
                    "INSERT INTO classes (day, subject, start_time, end_time) VALUES (?, ?, ?, ?)",
                    (day, subject.strip(), start_t.strftime("%H:%M"), end_t.strftime("%H:%M")),
                )
                st.success(f"Added {subject} on {day}.")
                st.rerun()

    classes_data = run_query("SELECT id, day, subject, start_time, end_time FROM classes ORDER BY day, start_time", fetch=True)
    if classes_data:
        df_classes = pd.DataFrame(classes_data, columns=["ID", "Day", "Subject", "Start", "End"])
        st.dataframe(df_classes.drop(columns=["ID"]), use_container_width=True, hide_index=True)
        
        del_id = st.selectbox("Select a class to remove", options=classes_data, format_func=lambda x: f"{x[1]}: {x[2]} ({x[3]}-{x[4]})")
        if st.button("Delete Selected Class"):
            run_query("DELETE FROM classes WHERE id = ?", (del_id[0],))
            st.rerun()
    else:
        st.info("No classes added yet. Add your fixed college timetable above.")

# --- TAB 2: TASKS & ASSIGNMENTS ---
with tab2:
    st.subheader("Add Study Tasks, Assignments & Goals")
    with st.form("task_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        title = c1.text_input("Task Name", placeholder="e.g., OS Lab Assignment")
        priority = c2.selectbox("Priority", ["High", "Medium", "Low"])
        duration = c3.number_input("Duration (mins)", min_value=15, max_value=240, value=60, step=15)
        deadline = c4.date_input("Deadline", value=datetime.today())
        task_sub = st.form_submit_button("Add Task")

        if task_sub:
            if not title.strip():
                st.error("Please enter a task name.")
            else:
                run_query(
                    "INSERT INTO tasks (title, priority, duration_mins, deadline) VALUES (?, ?, ?, ?)",
                    (title.strip(), priority, int(duration), deadline.strftime("%Y-%m-%d")),
                )
                st.success(f"Task '{title}' added.")
                st.rerun()

    tasks_data = run_query("SELECT id, title, priority, duration_mins, deadline, completed FROM tasks ORDER BY completed, deadline", fetch=True)
    if tasks_data:
        for tid, title, prio, dur, dl, comp in tasks_data:
            col_a, col_b, col_c = st.columns([5, 2, 1])
            status_text = f"~{title}~" if comp else f"*{title}*"
            col_a.markdown(f"{status_text} — {prio} | {dur} mins | Due: {dl}")
            if col_b.button("Mark Pending" if comp else "Mark Done", key=f"done_{tid}"):
                run_query("UPDATE tasks SET completed = ? WHERE id = ?", (0 if comp else 1, tid))
                st.rerun()
            if col_c.button("Delete", key=f"del_{tid}"):
                run_query("DELETE FROM tasks WHERE id = ?", (tid,))
                st.rerun()
    else:
        st.info("No tasks added yet. Add your assignments or study goals above.")

# --- TAB 3: AUTO-GENERATED SCHEDULE ---
with tab3:
    st.subheader("Fix Your Daily Schedule Automatically")
    col1, col2, col3, col4 = st.columns(4)
    sel_day = col1.selectbox("Select Day to Plan", DAYS)
    wake_t = col2.time_input("Wake-up / Start Time", value=time(7, 0))
    sleep_t = col3.time_input("Sleep / End Time", value=time(22, 30))
    break_len = col4.number_input("Break Between Tasks (mins)", min_value=5, max_value=30, value=10, step=5)

    if wake_t >= sleep_t:
        st.error("Sleep time must be later than wake-up time.")
    else:
        sched_df, unscheduled = generate_daily_schedule(
            sel_day,
            wake_t.hour * 60 + wake_t.minute,
            sleep_t.hour * 60 + sleep_t.minute,
            int(break_len),
        )

        if not sched_df.empty:
            st.dataframe(sched_df, use_container_width=True, hide_index=True)
            csv = sched_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download Schedule as CSV", data=csv, file_name=f"{sel_day}_schedule.csv", mime="text/csv")
        else:
            st.info(f"No classes or pending tasks scheduled for {sel_day}.")

        if unscheduled:
            st.warning("These tasks couldn't fit into today's free slots: " + ", ".join(unscheduled))
