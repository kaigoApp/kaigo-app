import os
import sqlite3
import html
from pathlib import Path
from datetime import date, datetime
import pandas as pd
import streamlit as st

# -------------------------
# 1. DB Path & Setup
# -------------------------
def resolve_db_path() -> Path:
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "tomogaki_proto.db"

DB_PATH = resolve_db_path()

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS units (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, is_active INTEGER DEFAULT 1);")
    conn.execute("CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER, name TEXT, is_active INTEGER DEFAULT 1, FOREIGN KEY(unit_id) REFERENCES units(id));")
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER, resident_id INTEGER, record_date TEXT, 
        record_time_hh INTEGER, record_time_mm INTEGER, shift TEXT, recorder_name TEXT, scene TEXT,
        note TEXT, is_report INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0,
        created_at TEXT, updated_at TEXT
    );""")
    if pd.read_sql_query("SELECT count(*) as c FROM units", conn).iloc[0]['c'] == 0:
        conn.execute("INSERT INTO units(name) VALUES ('ユニットA')")
        uid = conn.execute("SELECT id FROM units LIMIT 1").fetchone()[0]
        for nm in ["佐藤 太郎", "鈴木 花子"]:
            conn.execute("INSERT INTO residents(unit_id, name) VALUES(?, ?)", (uid, nm))
    conn.commit()

# -------------------------
# 2. UI Layout Adjustments
# -------------------------
st.set_page_config(layout="wide", page_title="介護記録アプリ")

# 表示崩れ対策のCSS
st.markdown("""
<style>
.stSelectbox label { font-size: 0.85rem !important; }
.record-card { background: white; padding: 15px; border-radius: 10px; border: 1px solid #eee; margin-bottom: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
.badge-warn { background: #ffeeba; color: #856404; padding: 2px 8px; border-radius: 5px; font-size: 0.8rem; font-weight: bold; margin-left: 5px; }
</style>
""", unsafe_allow_html=True)

# -------------------------
# 3. Main App Logic
# -------------------------
def page_daily(conn):
    st.title("📝 介護記録アプリ")
    
    # 利用者・日付選択
    unit_df = pd.read_sql_query("SELECT id, name FROM units", conn)
    unit_name = st.sidebar.selectbox("ユニット", unit_df["name"].tolist())
    unit_id = int(unit_df[unit_df["name"]==unit_name]["id"].iloc[0])
    target_date = st.sidebar.date_input("日付", value=date.today())
    recorder = st.sidebar.text_input("記録者名", value=st.session_state.get("recorder", ""))
    st.session_state["recorder"] = recorder

    res_df = pd.read_sql_query("SELECT id, name FROM residents WHERE unit_id=? AND is_active=1", conn, params=(unit_id,))
    selected_name = st.selectbox("利用者を選択", ["-- 選択してください --"] + res_df["name"].tolist())
    
    if selected_name != "-- 選択してください --":
        rid = int(res_df[res_df["name"]==selected_name]["id"].iloc[0])
        
        st.subheader(f"✍️ {selected_name} 様の支援記録")
        
        # スマホでの「分」の改行を防ぐため、比率を調整
        c1, c2, c3, c4 = st.columns([1, 1, 2, 1.5])
        with c1:
            hh = st.selectbox("時", ["未"] + list(range(0, 24)))
        with c2:
            # ラベルを「分」に短縮して改行を防止
            mm = st.selectbox("分", ["未"] + list(range(0, 60, 5)))
        with c3:
            scene = st.selectbox("場面", ["ご様子", "食事", "入浴", "外出", "その他"])
        with c4:
            is_rep = st.checkbox("申し送り", help="重要な情報を共有します")
            
        note = st.text_area("記録内容（フリーワード）", placeholder="具体的な様子を入力してください")

        if st.button("記録を保存する", use_container_width=True):
            if not recorder:
                st.error("左メニューから記録者名を入力してください")
            else:
                now = datetime.now().isoformat()
                conn.execute("""INSERT INTO daily_records (unit_id, resident_id, record_date, record_time_hh, record_time_mm, shift, recorder_name, scene, note, is_report, created_at, updated_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (unit_id, rid, target_date.isoformat(), hh if hh!="未" else None, mm if mm!="未" else None, "日勤", recorder, scene, note, 1 if is_rep else 0, now, now))
                conn.commit()
                st.success("保存しました！")
                st.rerun()

    # 履歴表示（HTMLタグ露出エラー修正済み）
    st.divider()
    st.subheader("支援記録一覧（履歴）")
    history = pd.read_sql_query("SELECT * FROM daily_records WHERE is_deleted=0 ORDER BY created_at DESC", conn)
    
    for _, row in history.iterrows():
        # html.escapeで安全に表示しつつ、バッジはHTMLとして描画
        safe_note = html.escape(str(row['note'] or ""))
        safe_scene = html.escape(str(row['scene'] or ""))
        safe_recorder = html.escape(str(row['recorder_name'] or ""))
        
        badge_html = "<span class='badge-warn'>申し送り</span>" if row['is_report'] else ""
        
        st.markdown(f"""
        <div class="record-card">
            <b>{row['record_time_hh'] or '--'}:{row['record_time_mm'] or '--'}</b> / {safe_scene} / 記録者 : {safe_recorder} {badge_html}
            <div style='margin-top:10px; border-top:1px solid #f0f0f0; padding-top:10px;'>
                ■ 記録内容：{safe_note}
            </div>
            <div style='font-size:0.7rem; color:#999; margin-top:10px; text-align:right;'>
                作成: {row['created_at'][:16].replace('T', ' ')}
            </div>
        </div>
        """, unsafe_allow_html=True)

# アプリ起動
conn = get_conn()
init_db(conn)
page_daily(conn)
