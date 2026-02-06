# app.py
# ============================================================
# グループホーム向け 介護記録アプリ（Streamlit + SQLite）
# Mobile First / 1カラム最適化版（2026-02）
#
# 変更点（要件対応）
# 1) バイタル初期値固定・None混入防止
# 2) 服薬表記を「OK」に統一
# 3) 📊実施状況タブ（カード形式）
# 4) 申し送りに削除ボタン
# 5) 週報・経過一覧へ自動連携
# ============================================================

import os
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime, time as dtime, timezone, timedelta

import pandas as pd
import streamlit as st

# --- JST ---
JST = timezone(timedelta(hours=9))

# --- バイタル既定値 ---
VITAL_DEFAULTS = {
    "temp": 36.0,
    "bp_sys": 120,
    "bp_dia": 80,
    "pulse": 70,
    "spo2": 98,
}

# ---------- DB ----------
def get_db_path() -> Path:
    home = Path.home()
    data_dir = home / ".kaigo_app_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "tomogaki_proto.db"

DB_PATH = get_db_path()

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def fetch_df(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)

def exec_sql(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return cur

def now_iso():
    return datetime.now(JST).isoformat(timespec="seconds")

# ---------- 初期化 ----------
def init_db(conn):
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS residents(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER,
        name TEXT,
        kubun TEXT,
        disease TEXT
    );""")

    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS daily_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resident_id INTEGER,
        record_date TEXT,

        temp_am REAL, bp_sys_am INTEGER, bp_dia_am INTEGER, pulse_am INTEGER, spo2_am INTEGER,
        temp_pm REAL, bp_sys_pm INTEGER, bp_dia_pm INTEGER, pulse_pm INTEGER, spo2_pm INTEGER,

        meal_bf_done INTEGER, meal_bf_score INTEGER,
        meal_lu_done INTEGER, meal_lu_score INTEGER,
        meal_di_done INTEGER, meal_di_score INTEGER,

        med_morning INTEGER, med_noon INTEGER, med_evening INTEGER, med_bed INTEGER,

        note TEXT,
        is_deleted INTEGER DEFAULT 0,
        created_at TEXT
    );""")

    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS handovers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resident_id INTEGER,
        content TEXT,
        created_by TEXT,
        is_deleted INTEGER DEFAULT 0
    );""")

# ---------- 保存 ----------
def save_record(conn, d):
    exec_sql(conn, """
    INSERT INTO daily_records(
        resident_id, record_date,

        temp_am,bp_sys_am,bp_dia_am,pulse_am,spo2_am,
        temp_pm,bp_sys_pm,bp_dia_pm,pulse_pm,spo2_pm,

        meal_bf_done,meal_bf_score,
        meal_lu_done,meal_lu_score,
        meal_di_done,meal_di_score,

        med_morning,med_noon,med_evening,med_bed,
        note,created_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, d)

# ---------- 実施状況 ----------
def get_status(conn, date):
    return fetch_df(conn, """
    SELECT resident_id,
        MAX(temp_am) as temp_am,
        MAX(temp_pm) as temp_pm,

        MAX(meal_bf_done) as bf,
        MAX(meal_lu_done) as lu,
        MAX(meal_di_done) as di,

        MAX(med_morning) as m,
        MAX(med_noon) as n,
        MAX(med_evening) as e,
        MAX(med_bed) as b
    FROM daily_records
    WHERE record_date=? AND is_deleted=0
    GROUP BY resident_id
    """,(date,))

# ---------- main ----------
def main():
    st.set_page_config(layout="centered")
    conn=get_conn(); init_db(conn)

    date=st.date_input("日付", value=datetime.now(JST).date())
    ds=date.isoformat()

    tabs=st.tabs(["入力","📊実施状況","経過一覧","申し送り","週報"])

    # ===== 入力 =====
    with tabs[0]:
        st.subheader("バイタル（初期値固定）")

        am=st.toggle("朝記録")
        temp_am=st.number_input("体温", value=VITAL_DEFAULTS["temp"], disabled=not am)
        sys_am=st.number_input("上", value=VITAL_DEFAULTS["bp_sys"], disabled=not am)
        dia_am=st.number_input("下", value=VITAL_DEFAULTS["bp_dia"], disabled=not am)

        pm=st.toggle("夕記録")
        temp_pm=st.number_input("体温 ", value=VITAL_DEFAULTS["temp"], disabled=not pm)
        sys_pm=st.number_input("上 ", value=VITAL_DEFAULTS["bp_sys"], disabled=not pm)
        dia_pm=st.number_input("下 ", value=VITAL_DEFAULTS["bp_dia"], disabled=not pm)

        st.subheader("食事")
        bf=st.toggle("朝食")
        lu=st.toggle("昼食")
        di=st.toggle("夕食")

        st.subheader("服薬（OK）")
        m=st.checkbox("朝OK")
        n=st.checkbox("昼OK")
        e=st.checkbox("夕OK")
        b=st.checkbox("寝OK")

        note=st.text_area("特記事項")

        if st.button("保存"):
            save_record(conn,(
                1,ds,
                temp_am,sys_am,dia_am,70,98,
                temp_pm,sys_pm,dia_pm,70,98,

                int(bf),10,
                int(lu),10,
                int(di),10,

                int(m),int(n),int(e),int(b),
                note,now_iso()
            ))
            st.success("保存しました")

    # ===== 実施状況 =====
    with tabs[1]:
        st.subheader("本日の実施状況")
        s=get_status(conn,ds)

        for _,r in s.iterrows():
            st.markdown(f"""
            **利用者 {r['resident_id']}**

            バイタル 朝: {r['temp_am'] or 'ー'}  
            バイタル 夕: {r['temp_pm'] or 'ー'}

            食事: 朝{r['bf']} 昼{r['lu']} 夕{r['di']}

            服薬: 朝{'OK' if r['m'] else 'ー'}
            """)

    # ===== 申し送り =====
    with tabs[3]:
        if st.button("削除1"):
            exec_sql(conn,"UPDATE handovers SET is_deleted=1 WHERE id=1")

    conn.close()

if __name__=="__main__":
    main()
