import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date

# --- ページ設定 (スマホで見やすく) ---
st.set_page_config(page_title="介護記録", layout="centered")

def inject_mobile_css():
    st.markdown("""
    <style>
    /* 全体フォントサイズ調整 */
    html, body, [class*="css"] { font-size: 16px !important; }
    /* ボタンを大きく押しやすく */
    .stButton > button {
        width: 100%;
        height: 3.5rem;
        border-radius: 12px;
        font-weight: bold;
        margin-bottom: 10px;
    }
    /* タイトルの調整 */
    .app-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-bottom: 1rem; }
    /* 赤文字強調（特記事項用） */
    .critical-note { color: #d32f2f !important; font-weight: bold; background: #ffebee; padding: 10px; border-radius: 8px; }
    /* 巡視カード */
    .patrol-card { border: 1px solid #ddd; padding: 10px; border-radius: 10px; margin-bottom: 10px; background: #fff; }
    </style>
    """, unsafe_allow_html=True)

inject_mobile_css()

# --- データベース準備 ---
DB_PATH = "care_records.db"
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # 利用者テーブル（区分・病名追加）
        conn.execute("""CREATE TABLE IF NOT EXISTS residents 
            (id INTEGER PRIMARY KEY, name TEXT, kubun TEXT, disease TEXT)""")
        # 記録テーブル
        conn.execute("""CREATE TABLE IF NOT EXISTS records 
            (id INTEGER PRIMARY KEY, resident_id INTEGER, record_time TEXT, 
             content TEXT, is_critical INTEGER, recorder TEXT)""")
        # 申し送り・いいねテーブル
        conn.execute("""CREATE TABLE IF NOT EXISTS handovers 
            (id INTEGER PRIMARY KEY, content TEXT, recorder TEXT, created_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS reactions 
            (handover_id INTEGER, user_name TEXT, UNIQUE(handover_id, user_name))""")
        
        # サンプルデータ（未登録時のみ）
        if not conn.execute("SELECT * FROM residents").fetchone():
            conn.execute("INSERT INTO residents (name, kubun, disease) VALUES ('佐藤 太郎', '区分4', '認知症')")

init_db()

# --- アプリケーション本体 ---
st.markdown('<div class="app-title">🧾 介護記録システム</div>', unsafe_allow_html=True)

# 記録者設定（一度入力したらセッションに保持）
if "recorder" not in st.session_state:
    st.session_state.recorder = ""

with st.sidebar:
    st.session_state.recorder = st.text_input("記録者氏名", value=st.session_state.recorder)
    target_date = st.date_input("記録日", date.today())

# タブ構成（スマホでの切り替えをスムーズに）
tab1, tab2, tab3 = st.tabs(["✍ 入力", "📋 経過", "📢 申し送り"])

with tab1:
    res_df = pd.read_sql("SELECT * FROM residents", get_db())
    selected_res = st.selectbox("利用者を選択", res_df["name"].tolist())
    res_id = res_df[res_df["name"] == selected_res]["id"].values[0]
    res_info = res_df[res_df["name"] == selected_res].iloc[0]

    st.caption(f"🏥 {res_info['kubun']} | {res_info['disease']}")

    # 巡視入力セクション
    st.subheader("巡視記録")
    p_time = st.time_input("巡視時刻（この時間が記録時刻になります）", datetime.now().time())
    p_status = st.selectbox("ご様子", ["就寝中", "覚醒・良", "排泄対応", "その他"])
    
    # 特記事項
    st.subheader("支援経過・特記事項")
    is_critical = st.checkbox("📢 特記事項あり（赤文字で強調）", value=False)
    
    # 特記事項ありならラベルを赤く
    note_label = "内容入力" if not is_critical else "⚠️ 特記事項の内容（赤文字反映）"
    note_content = st.text_area(note_label)

    # 保存ボタン（特記事項ありなら赤くする指示はCSSで実施）
    save_color = "primary" if not is_critical else "secondary"
    if st.button("記録を保存する", type=save_color):
        if not st.session_state.recorder:
            st.error("記録者名を入力してください")
        else:
            with get_db() as conn:
                full_time = f"{target_date} {p_time.strftime('%H:%M')}"
                combined_content = f"【巡視: {p_status}】 {note_content}"
                conn.execute("INSERT INTO records (resident_id, record_time, content, is_critical, recorder) VALUES (?,?,?,?,?)",
                             (int(res_id), full_time, combined_content, 1 if is_critical else 0, st.session_state.recorder))
                # 特記事項があれば自動で申し送りへ
                if is_critical:
                    conn.execute("INSERT INTO handovers (content, recorder, created_at) VALUES (?,?,?)",
                                 (f"{selected_res}: {combined_content}", st.session_state.recorder, full_time))
            st.success("保存しました！")
            st.rerun()

with tab2:
    st.subheader("支援経過記録一覧")
    records = pd.read_sql(f"SELECT * FROM records WHERE resident_id = {res_id} ORDER BY record_time DESC", get_db())
    for _, row in records.iterrows():
        # 特記事項は赤文字、通常はそのまま
        if row['is_critical']:
            st.markdown(f"🔴 **{row['record_time']}**")
            st.markdown(f'<div class="critical-note">{row["content"]}（記: {row["recorder"]}）</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"⚪ **{row['record_time']}**")
            st.info(f"{row['content']}（記: {row['recorder']}）")

with tab3:
    st.subheader("職員申し送り（いいねで確認）")
    h_df = pd.read_sql("SELECT * FROM handovers ORDER BY id DESC", get_db())
    for _, h in h_df.iterrows():
        with st.container():
            st.markdown(f"**{h['created_at']}**")
            st.warning(h['content'])
            
            # いいね機能
            reactions = pd.read_sql(f"SELECT user_name FROM reactions WHERE handover_id = {h['id']}", get_db())
            user_list = reactions['user_name'].tolist()
            count = len(user_list)
            
            cols = st.columns([0.3, 0.7])
            with cols[0]:
                if st.button(f"👍 {count}", key=f"like_{h['id']}"):
                    if st.session_state.recorder and st.session_state.recorder not in user_list:
                        with get_db() as conn:
                            conn.execute("INSERT INTO reactions (handover_id, user_name) VALUES (?,?)", (int(h['id']), st.session_state.recorder))
                        st.rerun()
            with cols[1]:
                if count > 0:
                    st.caption(f"確認済: {', '.join(user_list)}")
