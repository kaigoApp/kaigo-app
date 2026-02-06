import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date

# --- 1. スマホ最適化CSS ---
def inject_mobile_css():
    st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 16px !important; }
    .stButton > button {
        width: 100%; height: 3.5rem; border-radius: 12px;
        font-weight: bold; margin-bottom: 10px;
    }
    .app-title { font-size: 1.4rem; font-weight: bold; text-align: center; padding: 10px; }
    .critical-text { color: #d32f2f !important; font-weight: bold; }
    .handover-card { background: #fff; border: 1px solid #ddd; padding: 15px; border-radius: 15px; margin-bottom: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .reaction-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データベース機能（②〜⑤の項目を保持） ---
DB_PATH = "care_records_v2.db"
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # 利用者マスター
        conn.execute("""CREATE TABLE IF NOT EXISTS residents 
            (id INTEGER PRIMARY KEY, name TEXT, kubun TEXT, disease TEXT)""")
        # 記録テーブル（巡視項目を含む）
        conn.execute("""CREATE TABLE IF NOT EXISTS records 
            (id INTEGER PRIMARY KEY, resident_id INTEGER, record_time TEXT, 
             scene TEXT, status TEXT, note TEXT, is_critical INTEGER, recorder TEXT)""")
        # 申し送り・いいね
        conn.execute("""CREATE TABLE IF NOT EXISTS handovers 
            (id INTEGER PRIMARY KEY, content TEXT, recorder TEXT, created_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS reactions 
            (handover_id INTEGER, user_name TEXT, UNIQUE(handover_id, user_name))""")
        
        # 利用者データの復活
        if not conn.execute("SELECT * FROM residents").fetchone():
            data = [
                ('佐藤 太郎', '区分4', '認知症'),
                ('鈴木 花子', '区分3', '肢体不自由'),
                ('田中 次郎', '区分5', '統合失調症'),
                ('山田 恒一', '区分2', '高次脳機能障害')
            ]
            conn.executemany("INSERT INTO residents (name, kubun, disease) VALUES (?,?,?)", data)

# --- 3. メイン処理 ---
inject_mobile_css()
init_db()

st.markdown('<div class="app-title">🧾 介護記録（スマホ最適化版）</div>', unsafe_allow_html=True)

# 記録者名の保持
if "recorder" not in st.session_state:
    st.session_state.recorder = ""

with st.sidebar:
    st.session_state.recorder = st.text_input("✍ 記録者氏名", value=st.session_state.recorder)
    target_date = st.date_input("📅 記録日", date.today())

tab1, tab2, tab3 = st.tabs(["✍ 入力", "📋 経過", "📢 申し送り"])

# --- タブ1: 入力 ---
with tab1:
    res_df = pd.read_sql("SELECT * FROM residents", get_db())
    # セレクトボックスを大きく（スマホ対応）
    selected_name = st.selectbox("👤 利用者を選択", res_df["name"].tolist())
    res_info = res_df[res_df["name"] == selected_name].iloc[0]
    st.caption(f"🏥 {res_info['kubun']} | {res_info['disease']}")

    st.divider()
    
    # 巡視の入力（時刻選択の自動連動）
    st.subheader("🌙 巡視・様子")
    p_time = st.time_input("巡視時刻（これが記録時刻になります）", datetime.now().time())
    p_status = st.selectbox("ご様子", ["就寝中", "安眠中", "覚醒", "トイレ介助", "離床", "その他"])
    
    # 特記事項の入力（赤文字連動）
    st.subheader("📝 支援内容・特記事項")
    note = st.text_area("内容を入力してください", placeholder="具体的な様子など")
    is_critical = st.checkbox("📢 【重要】特記事項として報告する", value=False)
    
    # 特記ありならボタンを赤く
    btn_label = "✅ 記録を保存" if not is_critical else "🚨 特記事項として保存"
    
    if st.button(btn_label):
        if not st.session_state.recorder:
            st.error("左メニューから『記録者名』を入力してください")
        else:
            with get_db() as conn:
                rec_time = f"{target_date} {p_time.strftime('%H:%M')}"
                conn.execute("""INSERT INTO records 
                    (resident_id, record_time, status, note, is_critical, recorder) 
                    VALUES (?,?,?,?,?,?)""",
                    (int(res_info['id']), rec_time, p_status, note, 1 if is_critical else 0, st.session_state.recorder))
                
                # 特記ありなら申し送りへ自動反映
                if is_critical:
                    conn.execute("INSERT INTO handovers (content, recorder, created_at) VALUES (?,?,?)",
                                 (f"{selected_name}: {p_status} / {note}", st.session_state.recorder, rec_time))
            st.success("保存完了！")
            st.rerun()

# --- タブ2: 経過一覧 ---
with tab2:
    st.subheader(f"📋 {selected_name} の経過")
    records = pd.read_sql(f"SELECT * FROM records WHERE resident_id = {res_info['id']} ORDER BY record_time DESC", get_db())
    
    for _, row in records.iterrows():
        with st.container():
            time_str = row['record_time'].split(" ")[1] # 時刻だけ抽出
            if row['is_critical']:
                st.markdown(f"🔴 **{time_str}** <span class='critical-text'>【特記】 {row['status']}</span>", unsafe_allow_html=True)
                st.markdown(f"<div class='critical-text'>{row['note']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"⚪ **{time_str}** {row['status']}")
                if row['note']: st.info(row['note'])
            st.caption(f"記録者: {row['recorder']}")
            st.divider()

# --- タブ3: 申し送り（いいね機能） ---
with tab3:
    st.subheader("📢 職員連絡帳")
    h_df = pd.read_sql("SELECT * FROM handovers ORDER BY id DESC LIMIT 20", get_db())
    
    for _, h in h_df.iterrows():
        st.markdown(f"""<div class="handover-card">
            <small>{h['created_at']} 投稿者: {h['recorder']}</small><br>
            <strong>{h['content']}</strong>
        </div>""", unsafe_allow_html=True)
        
        # リアクション（いいね）機能
        reactions = pd.read_sql(f"SELECT user_name FROM reactions WHERE handover_id = {h['id']}", get_db())
        user_list = reactions['user_name'].tolist()
        
        # 誰が押したか表示
        cols = st.columns([0.2, 0.8])
        with cols[0]:
            if st.button(f"👍 {len(user_list)}", key=f"h_{h['id']}"):
                if st.session_state.recorder and st.session_state.recorder not in user_list:
                    with get_db() as conn:
                        conn.execute("INSERT INTO reactions (handover
