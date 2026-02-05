import os
import sqlite3
import html
from pathlib import Path
from datetime import date, datetime
import pandas as pd
import streamlit as st

# 1. データベースの自動準備
def get_db_conn():
    db_path = Path("data/kaigo_pro_v1.db")
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY, name TEXT UNIQUE);")
    conn.execute("""CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, res_id INTEGER, record_date TEXT, 
        hh INTEGER, mm INTEGER, recorder TEXT, scene TEXT, note TEXT, created_at TEXT
    );""")
    # 利用者さんリスト（ここを書き換えるだけで何人でも増やせます！）
    names = ["佐藤 太郎", "鈴木 花子", "高橋 一郎", "田中 幸子"]
    for name in names:
        conn.execute("INSERT OR IGNORE INTO residents(name) VALUES (?)", (name,))
    conn.commit()

# 2. スマホ・PC共通の見た目調整（CSS）
st.set_page_config(page_title="介護記録アプリ", layout="wide")
st.markdown("""
<style>
    .stButton>button { width: 100%; height: 3.5em; font-weight: bold; border-radius: 12px; }
    .res-card { background: #ffffff; padding: 15px; border-radius: 15px; border: 1px solid #e0e0e0; 
                border-left: 8px solid #4CAF50; box-shadow: 2px 2px 8px rgba(0,0,0,0.05); }
    div[data-testid="stExpander"] { border-radius: 15px; background: #fdfdfd; }
</style>
""", unsafe_allow_html=True)

conn = get_db_conn()
init_db(conn)

# --- メイン画面 ---
st.title("📝 介護記録システム")

# サイドバー設定
st.sidebar.header("⚙️ 設定・検索")
target_date = st.sidebar.date_input("日付を選択", value=date.today())
recorder = st.sidebar.text_input("記録者名（必須）", value=st.session_state.get("recorder", ""))
st.session_state["recorder"] = recorder

# 利用者選択の状態管理
if "active_res_id" not in st.session_state:
    st.session_state.active_res_id = None

if st.session_state.active_res_id is None:
    # 🏠 利用者一覧（トップ画面）
    st.subheader(f"👥 利用者を選択してください（{target_date}）")
    res_df = pd.read_sql_query("SELECT * FROM residents", conn)
    
    # 2列でカードを表示
    cols = st.columns(2)
    for i, row in res_df.iterrows():
        with cols[i % 2]:
            st.markdown(f'<div class="res-card"><b>{row["name"]} 様</b></div>', unsafe_allow_html=True)
            if st.button(f"記録を入力・確認", key=f"sel_{row['id']}"):
                st.session_state.active_res_id = row['id']
                st.session_state.active_res_name = row['name']
                st.rerun()
else:
    # ✍️ 個別記録画面
    st.button("🔙 一覧に戻る", on_click=lambda: st.session_state.update({"active_res_id": None}))
    st.header(f"👤 {st.session_state.active_res_name} 様")
    
    # 入力フォーム
    with st.container(border=True):
        st.write("▼ 新規記録")
        c1, c2 = st.columns(2)
        with c1:
            hh = st.selectbox("時", list(range(24)), index=datetime.now().hour)
        with c2:
            mm = st.selectbox("分", list(range(0, 60, 5)), index=(datetime.now().minute // 5) * 5 // 5 if datetime.now().minute < 60 else 0)
        
        # 場面をボタンで選択
        scene = st.radio("場面", ["ご様子", "食事", "排泄", "入浴", "睡眠", "その他", "受診"], horizontal=True)
        note = st.text_area("内容（自由記述）", placeholder="具体的な様子を入力してください...", height=100)
        
        if st.button("💾 記録を保存する", type="primary"):
            if not recorder:
                st.error("先に左メニューで『記録者名』を入力してください")
            else:
                now = datetime.now().isoformat()
                conn.execute("INSERT INTO records (res_id, record_date, hh, mm, recorder, scene, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                             (st.session_state.active_res_id, str(target_date), hh, mm, recorder, scene, note, now))
                conn.commit()
                st.success(f"{st.session_state.active_res_name}様の記録を保存しました！")
                st.rerun()

    # 履歴表示
    st.divider()
    st.subheader("📋 最近の履歴（5件）")
    history = pd.read_sql_query("SELECT * FROM records WHERE res_id=? ORDER BY created_at DESC LIMIT 5", conn, params=(st.session_state.active_res_id,))
    if history.empty:
        st.write("まだ本日の記録はありません。")
    for _, h in history.iterrows():
        with st.chat_message("user"):
            st.write(f"**{h['hh']:02}:{h['mm']:02} 【{h['scene']}】** 記録者: {h['recorder']}")
            st.write(h['note'])
