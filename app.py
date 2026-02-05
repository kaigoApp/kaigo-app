import sqlite3
from pathlib import Path
from datetime import date, datetime
import pandas as pd
import streamlit as st

# 1. データベース設定
def get_db_conn():
    db_path = Path("data/kaigo_full_v1.db")
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY, name TEXT UNIQUE);")
    conn.execute("""CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, res_id INTEGER, record_date TEXT, 
        hh INTEGER, mm INTEGER, recorder TEXT, category TEXT, 
        v_temp REAL, v_bp_h INTEGER, v_bp_l INTEGER, v_pulse INTEGER,
        food TEXT, water TEXT, medicine TEXT, note TEXT, created_at TEXT
    );""")
    names = ["佐藤 太郎", "鈴木 花子", "高橋 一郎", "田中 幸子"]
    for name in names:
        conn.execute("INSERT OR IGNORE INTO residents(name) VALUES (?)", (name,))
    conn.commit()

# 2. デザイン（スマホ最適化）
st.set_page_config(page_title="介護記録Pro", layout="wide")
st.markdown("""
<style>
    .stButton>button { width: 100%; height: 3em; border-radius: 10px; font-weight: bold; }
    .res-card { background: #ffffff; padding: 15px; border-radius: 12px; border-left: 10px solid #4CAF50; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 5px; }
    .cate-badge { background: #e8f5e9; color: #2e7d32; padding: 2px 8px; border-radius: 5px; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

conn = get_db_conn()
init_db(conn)

# --- アプリ本体 ---
st.title("🏥 総合介護管理システム")

# サイドバー
st.sidebar.header("📋 基本情報")
target_date = st.sidebar.date_input("記録日", value=date.today())
recorder = st.sidebar.text_input("記録者名", value=st.session_state.get("recorder", ""))
st.session_state["recorder"] = recorder

if "res_id" not in st.session_state: st.session_state.res_id = None

if st.session_state.res_id is None:
    # 利用者一覧
    res_df = pd.read_sql_query("SELECT * FROM residents", conn)
    cols = st.columns(2)
    for i, row in res_df.iterrows():
        with cols[i % 2]:
            st.markdown(f'<div class="res-card"><b>{row["name"]} 様</b></div>', unsafe_allow_html=True)
            if st.button(f"選択", key=f"res_{row['id']}"):
                st.session_state.res_id, st.session_state.res_name = row['id'], row['name']
                st.rerun()
else:
    # 個別入力画面
    st.button("🔙 一覧に戻る", on_click=lambda: st.session_state.update({"res_id": None}))
    st.header(f"👤 {st.session_state.res_name} 様")

    # カテゴリ選択（タブで切り替え）
    tab1, tab2, tab3, tab4 = st.tabs(["🌡 バイタル", "🍱 食事/薬", "🚽 排泄/巡視", "📝 その他"])

    with tab1:
        c1, c2, c3 = st.columns(3)
        v_temp = c1.number_input("体温", 34.0, 42.0, 36.5, 0.1)
        v_bp_h = c2.number_input("血圧(上)", 50, 250, 120)
        v_bp_l = c3.number_input("血圧(下)", 30, 150, 80)
        v_pulse = st.number_input("脈拍", 30, 200, 70)

    with tab2:
        food = st.select_slider("食事摂取量", options=["0%", "25%", "50%", "75%", "100%"], value="100%")
        water = st.select_slider("水分(ml)", options=["0", "50", "100", "150", "200", "250+"], value="100")
        medicine = st.radio("服薬", ["なし", "内服済", "頓服", "拒薬"], horizontal=True)

    with tab3:
        excretion = st.radio("排泄", ["なし", "排尿あり", "排便あり", "両方あり"], horizontal=True)
        patrol = st.radio("巡視", ["異常なし", "入眠中", "覚醒", "その他"], horizontal=True)

    with tab4:
        category = st.selectbox("記録種別", ["通常記録", "受診", "事故/ヒヤリ", "ご家族連絡"])
        note = st.text_area("備考/詳細", height=100)

    if st.button("💾 この内容で記録を保存", type="primary"):
        if not recorder:
            st.error("記録者名を入力してください")
        else:
            # 入力情報をまとめてメモ化
            summary = f"【排泄】{excretion} 【巡視】{patrol} {note}"
            conn.execute("""INSERT INTO records (res_id, record_date, hh, mm, recorder, category, 
                         v_temp, v_bp_h, v_bp_l, v_pulse, food, water, medicine, note, created_at) 
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (st.session_state.res_id, str(target_date), datetime.now().hour, datetime.now().minute, 
                          recorder, "総合記録", v_temp, v_bp_h, v_bp_l, v_pulse, food, water, medicine, summary, datetime.now().isoformat()))
            conn.commit()
            st.success("保存完了！")
            st.rerun()

    # 履歴表示
    st.divider()
    st.subheader("📋 履歴")
    hist = pd.read_sql_query("SELECT * FROM records WHERE res_id=? ORDER BY created_at DESC LIMIT 5", conn, params=(st.session_state.res_id,))
    for _, h in hist.iterrows():
        with st.expander(f"🕒 {h['hh']:02}:{h['mm']:02} - {h['recorder']}"):
            st.write(f"🌡 {h['v_temp']}℃ / {h['v_bp_h']}-{h['v_bp_l']} / 💓 {h['v_pulse']}")
            st.write(f"🍱 食事:{h['food']} / 💧 水分:{h['water']}ml / 💊 服薬:{h['medicine']}")
            st.write(f"📝 {h['note']}")
