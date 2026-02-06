import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date

# --- 1. ページ設定 & スマホ用CSS ---
st.set_page_config(page_title="介護記録アプリ", layout="wide")

def inject_mobile_css():
    st.markdown("""
    <style>
    .stButton > button { width: 100%; border-radius: 10px; height: 3rem; font-weight: bold; }
    .res-card { background: white; border-radius: 15px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 5px solid #2e7d32; margin-bottom: 15px; }
    .critical-card { background: #fff5f5; border-left: 5px solid #d32f2f; padding: 15px; border-radius: 10px; margin-bottom: 10px; }
    .app-header { font-size: 1.8rem; font-weight: bold; color: #333; margin-bottom: 20px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

inject_mobile_css()

# --- 2. データベース初期化 ---
DB_PATH = "care_app_v3.db"
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY, name TEXT, kubun TEXT, disease TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, res_id INTEGER, time TEXT, status TEXT, note TEXT, is_critical INTEGER, recorder TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS handovers (id INTEGER PRIMARY KEY, content TEXT, recorder TEXT, time TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS likes (h_id INTEGER, user TEXT, UNIQUE(h_id, user))")
        
        if not conn.execute("SELECT * FROM residents").fetchone():
            users = [('佐藤 太郎', '区分4', '認知症'), ('山田 恒一', '区分2', '高次脳機能障害'), 
                     ('田中 次郎', '区分5', '統合失調症'), ('鈴木 花子', '区分3', '肢体不自由')]
            conn.executemany("INSERT INTO residents (name, kubun, disease) VALUES (?,?,?)", users)

init_db()

# --- 3. サイドバー設定 ---
with st.sidebar:
    st.header("⚙ 設定")
    target_date = st.date_input("記録日", date.today())
    shift = st.radio("勤務区分", ["日勤", "夜勤"])
    recorder = st.text_input("記録者名（必須）", placeholder="例：毛利 正二")

# --- 4. メイン画面 ---
st.markdown('<div class="app-header">📑 介護記録システム</div>', unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["👥 利用者一覧", "✍ 記録入力", "📢 申し送り"])

# --- TAB 1: 利用者一覧（カード形式） ---
with tab1:
    res_df = pd.read_sql("SELECT * FROM residents", get_db())
    cols = st.columns(2)
    for idx, row in res_df.iterrows():
        with cols[idx % 2]:
            st.markdown(f"""
            <div class="res-card">
                <h3>{row['name']}</h3>
                <p>区分: {row['kubun']} / 病名: {row['disease']}</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"{row['name']}さんを選択", key=f"sel_{row['id']}"):
                st.session_state.selected_res = row['name']
                st.session_state.selected_id = row['id']
                st.success(f"{row['name']}さんを選択しました。「記録入力」タブへ進んでください。")

# --- TAB 2: 記録入力 ---
with tab2:
    if "selected_res" not in st.session_state:
        st.warning("「利用者一覧」から対象者を選択してください。")
    else:
        st.subheader(f"✍ {st.session_state.selected_res} さんの記録")
        
        c1, c2 = st.columns(2)
        with c1:
            p_time = st.time_input("巡視時刻", datetime.now().time())
        with c2:
            p_status = st.selectbox("様子", ["安眠中", "就寝中", "覚醒", "排泄介助", "離床中"])
        
        note = st.text_area("内容・特記事項", placeholder="普段と違う様子があれば記入")
        is_critical = st.checkbox("🚨 特記事項（申し送りにも自動反映）")
        
        if st.button("この内容で保存する"):
            if not recorder:
                st.error("サイドバーで記録者名を入力してください。")
            else:
                full_time = f"{target_date} {p_time.strftime('%H:%M')}"
                with get_db() as conn:
                    conn.execute("INSERT INTO records (res_id, time, status, note, is_critical, recorder) VALUES (?,?,?,?,?,?)",
                                 (st.session_state.selected_id, full_time, p_status, note, 1 if is_critical else 0, recorder))
                    if is_critical:
                        conn.execute("INSERT INTO handovers (content, recorder, time) VALUES (?,?,?)",
                                     (f"{st.session_state.selected_res}: {p_status} / {note}", recorder, full_time))
                st.success("記録を保存しました！")

# --- TAB 3: 申し送り ---
with tab3:
    st.subheader("📢 職員申し送り一覧")
    h_df = pd.read_sql("SELECT * FROM handovers ORDER BY id DESC", get_db())
    for _, h in h_df.iterrows():
        st.markdown(f"""<div class="critical-card">
            <small>{h['time']} 記入者: {h['recorder']}</small><br>
            <strong>{h['content']}</strong>
        </div>""", unsafe_allow_html=True)
        
        # いいね機能
        likes = pd.read_sql(f"SELECT user FROM likes WHERE h_id = {h['id']}", get_db())
        user_list = likes['user'].tolist()
        if st.button(f"👍 確認済 {len(user_list)}", key=f"lk_{h['id']}"):
            if recorder and recorder not in user_list:
                with get_db() as conn:
                    conn.execute("INSERT INTO likes (h_id, user) VALUES (?,?)", (h['id'], recorder))
                st.rerun()
        if user_list:
            st.caption(f"確認者: {', '.join(user_list)}")
