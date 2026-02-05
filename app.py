# app.py
# ============================================================
# 介護記録アプリ（Streamlit + SQLite）
# - 監査対応：保存は常に INSERT / 削除は論理削除
# - スマホ最適化：入力1行レイアウト、ラベル改行対策
# - 特記事項(note)がある履歴は赤文字＋要確認バッジ
# - 申し送りボード：黒文字（コピペ優先）＋確認ボタン
# - DBパス：secrets / env / data/ に保存（Cloud対応）
# ============================================================

import os
import sqlite3
import html
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st


# -------------------------
# DB Path (Cloud ready)
# -------------------------
def resolve_db_path() -> Path:
    """
    優先順：
      1) st.secrets["DB_PATH"]
      2) env: TOMOGAKI_DB_PATH / DB_PATH
      3) app_dir/data/tomogaki_proto.db
    """
    secrets_path = None
    try:
        secrets_path = st.secrets.get("DB_PATH", None)
    except Exception:
        secrets_path = None

    env_path = os.getenv("TOMOGAKI_DB_PATH") or os.getenv("DB_PATH")

    raw = secrets_path or env_path
    if raw:
        p = Path(str(raw)).expanduser()
        if str(p).endswith(("/", "\\")) or (p.exists() and p.is_dir()):
            p = p / "tomogaki_proto.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    base = Path(__file__).resolve().parent
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "tomogaki_proto.db"


DB_PATH = resolve_db_path()


# -------------------------
# DB helpers
# -------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def fetch_df(conn, sql, params=None):
    if params is None:
        params = {}
    return pd.read_sql_query(sql, conn, params=params)


def exec_sql(conn, sql, params=None):
    if params is None:
        params = {}
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return cur


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_table_cols(conn, table: str) -> set:
    df = fetch_df(conn, f"PRAGMA table_info({table});")
    return set(df["name"].tolist()) if not df.empty else set()


def ensure_column(conn, table: str, col: str, col_def_sql: str):
    cols = get_table_cols(conn, table)
    if col not in cols:
        exec_sql(conn, f"ALTER TABLE {table} ADD COLUMN {col_def_sql};")


def init_db(conn):
    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        """,
    )

    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS residents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE
        );
        """,
    )

    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL,
            resident_id INTEGER NOT NULL,

            record_date TEXT NOT NULL,
            record_time_hh INTEGER,
            record_time_mm INTEGER,

            shift TEXT NOT NULL,
            recorder_name TEXT NOT NULL,

            scene TEXT,
            scene_note TEXT,

            meal_bf_done INTEGER NOT NULL DEFAULT 0,
            meal_bf_score INTEGER NOT NULL DEFAULT 0,
            meal_lu_done INTEGER NOT NULL DEFAULT 0,
            meal_lu_score INTEGER NOT NULL DEFAULT 0,
            meal_di_done INTEGER NOT NULL DEFAULT 0,
            meal_di_score INTEGER NOT NULL DEFAULT 0,

            med_morning INTEGER NOT NULL DEFAULT 0,
            med_noon INTEGER NOT NULL DEFAULT 0,
            med_evening INTEGER NOT NULL DEFAULT 0,
            med_bed INTEGER NOT NULL DEFAULT 0,

            note TEXT,
            is_report INTEGER NOT NULL DEFAULT 0,
            is_confirmed INTEGER NOT NULL DEFAULT 0,

            is_deleted INTEGER NOT NULL DEFAULT 0,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE,
            FOREIGN KEY(resident_id) REFERENCES residents(id) ON DELETE CASCADE
        );
        """,
    )

    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS daily_patrols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            patrol_no INTEGER NOT NULL,
            patrol_time_hh INTEGER,
            patrol_time_mm INTEGER,
            status TEXT,
            memo TEXT,
            intervened INTEGER NOT NULL DEFAULT 0,
            door_opened INTEGER NOT NULL DEFAULT 0,
            safety_checks TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(record_id) REFERENCES daily_records(id) ON DELETE CASCADE
        );
        """,
    )

    # vitals columns
    ensure_column(conn, "daily_records", "temp_am", "temp_am REAL")
    ensure_column(conn, "daily_records", "bp_sys_am", "bp_sys_am INTEGER")
    ensure_column(conn, "daily_records", "bp_dia_am", "bp_dia_am INTEGER")
    ensure_column(conn, "daily_records", "pulse_am", "pulse_am INTEGER")
    ensure_column(conn, "daily_records", "spo2_am", "spo2_am INTEGER")

    ensure_column(conn, "daily_records", "temp_pm", "temp_pm REAL")
    ensure_column(conn, "daily_records", "bp_sys_pm", "bp_sys_pm INTEGER")
    ensure_column(conn, "daily_records", "bp_dia_pm", "bp_dia_pm INTEGER")
    ensure_column(conn, "daily_records", "pulse_pm", "pulse_pm INTEGER")
    ensure_column(conn, "daily_records", "spo2_pm", "spo2_pm INTEGER")

    # seed
    units = fetch_df(conn, "SELECT id FROM units LIMIT 1;")
    if units.empty:
        exec_sql(conn, "INSERT INTO units(name) VALUES (:name)", {"name": "ユニットA"})
        exec_sql(conn, "INSERT INTO units(name) VALUES (:name)", {"name": "ユニットB"})

    res = fetch_df(conn, "SELECT id FROM residents LIMIT 1;")
    if res.empty:
        u = fetch_df(conn, "SELECT id, name FROM units ORDER BY id;")
        unit_a = int(u.loc[0, "id"])
        unit_b = int(u.loc[1, "id"]) if len(u) > 1 else unit_a
        for nm in ["佐藤 太郎", "鈴木 花子", "田中 次郎", "山田 恒一"]:
            exec_sql(conn, "INSERT INTO residents(unit_id, name) VALUES(:uid,:nm)", {"uid": unit_a, "nm": nm})
        for nm in ["高橋 美咲", "伊藤 恒一"]:
            exec_sql(conn, "INSERT INTO residents(unit_id, name) VALUES(:uid,:nm)", {"uid": unit_b, "nm": nm})


# -------------------------
# UI helpers
# -------------------------
SCENES = ["", "ご様子", "起床", "食事", "入浴", "就寝前", "外出", "通所", "服薬", "対人", "金銭", "帰設", "その他"]
SCENE_LABEL = {"": "未選択"}

PATROL_STATUS_OPTIONS = ["", "就寝中（静か）", "起きている（静か）", "起きている（落ち着かない）", "不穏", "不在"]
SAFETY_OPTIONS = ["室温OK", "体調変化なし", "危険物なし", "転倒リスクなし"]


def scene_display(s: str) -> str:
    if s is None:
        return "未選択"
    s = str(s)
    return SCENE_LABEL.get(s, s)


def is_blank(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def safe_float(v):
    if is_blank(v):
        return None
    try:
        return float(v)
    except Exception:
        return None


def safe_int(v):
    if is_blank(v):
        return None
    f = safe_float(v)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def hhmm(hh, mm) -> str:
    ih = safe_int(hh)
    im = safe_int(mm)
    if ih is None or im is None:
        return "--:--"
    return f"{ih:02d}:{im:02d}"


# ✅ ここがポイント：streamlit.escape は使わず、標準 html.escape を使う
def esc(s: str) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def to_html_lines(s: str) -> str:
    return esc(s).replace("\n", "<br>")


def build_vital_inline(row) -> str:
    parts = []

    am_parts = []
    t = safe_float(row.get("temp_am"))
    if t is not None and abs(t) > 1e-12:
        am_parts.append(f"体温 {t:.1f}")
    sys = safe_int(row.get("bp_sys_am"))
    dia = safe_int(row.get("bp_dia_am"))
    if sys and dia:
        am_parts.append(f"血圧 {sys}/{dia}")
    pulse = safe_int(row.get("pulse_am"))
    if pulse:
        am_parts.append(f"脈拍 {pulse}")
    spo2 = safe_int(row.get("spo2_am"))
    if spo2:
        am_parts.append(f"SpO₂ {spo2}")

    pm_parts = []
    t2 = safe_float(row.get("temp_pm"))
    if t2 is not None and abs(t2) > 1e-12:
        pm_parts.append(f"体温 {t2:.1f}")
    sys2 = safe_int(row.get("bp_sys_pm"))
    dia2 = safe_int(row.get("bp_dia_pm"))
    if sys2 and dia2:
        pm_parts.append(f"血圧 {sys2}/{dia2}")
    pulse2 = safe_int(row.get("pulse_pm"))
    if pulse2:
        pm_parts.append(f"脈拍 {pulse2}")
    spo22 = safe_int(row.get("spo2_pm"))
    if spo22:
        pm_parts.append(f"SpO₂ {spo22}")

    if am_parts:
        parts.append("朝: " + " / ".join(am_parts))
    if pm_parts:
        parts.append("夕: " + " / ".join(pm_parts))
    return "｜".join(parts)


# -------------------------
# epoch keys
# -------------------------
ADD_EPOCH_KEY = "add_epoch"


def ensure_epochs():
    if ADD_EPOCH_KEY not in st.session_state:
        st.session_state[ADD_EPOCH_KEY] = 0


def wkey(name: str) -> str:
    return f"{name}__e{st.session_state[ADD_EPOCH_KEY]}"


def maybe_toast():
    msg = st.session_state.pop("__toast__", None)
    if msg:
        try:
            st.toast(msg)
        except Exception:
            st.success(msg)


def bump_add_epoch_and_rerun(msg: str):
    st.session_state[ADD_EPOCH_KEY] = int(st.session_state[ADD_EPOCH_KEY]) + 1
    st.session_state["__toast__"] = msg
    st.rerun()


# -------------------------
# Records / Patrols
# -------------------------
def insert_record(conn, payload: dict, patrols: list):
    now = now_iso()
    payload2 = dict(payload)
    payload2["created_at"] = now
    payload2["updated_at"] = now
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO daily_records(
            unit_id, resident_id,
            record_date, record_time_hh, record_time_mm,
            shift, recorder_name,
            scene, scene_note,

            temp_am, bp_sys_am, bp_dia_am, pulse_am, spo2_am,
            temp_pm, bp_sys_pm, bp_dia_pm, pulse_pm, spo2_pm,

            meal_bf_done, meal_bf_score,
            meal_lu_done, meal_lu_score,
            meal_di_done, meal_di_score,

            med_morning, med_noon, med_evening, med_bed,
            note, is_report, is_confirmed,
            is_deleted, created_at, updated_at
        )
        VALUES(
            :unit_id, :resident_id,
            :record_date, :record_time_hh, :record_time_mm,
            :shift, :recorder_name,
            :scene, :scene_note,

            :temp_am, :bp_sys_am, :bp_dia_am, :pulse_am, :spo2_am,
            :temp_pm, :bp_sys_pm, :bp_dia_pm, :pulse_pm, :spo2_pm,

            :meal_bf_done, :meal_bf_score,
            :meal_lu_done, :meal_lu_score,
            :meal_di_done, :meal_di_score,

            :med_morning, :med_noon, :med_evening, :med_bed,
            :note, :is_report, :is_confirmed,
            0, :created_at, :updated_at
        )
        """,
        payload2,
    )
    record_id = int(cur.lastrowid)

    for p in patrols:
        cur.execute(
            """
            INSERT INTO daily_patrols(
                record_id, patrol_no, patrol_time_hh, patrol_time_mm,
                status, memo, intervened, door_opened, safety_checks, created_at
            )
            VALUES(:record_id,:patrol_no,:patrol_time_hh,:patrol_time_mm,:status,:memo,:intervened,:door_opened,:safety_checks,:created_at)
            """,
            {
                "record_id": record_id,
                "patrol_no": safe_int(p.get("patrol_no")) or 0,
                "patrol_time_hh": p.get("patrol_time_hh"),
                "patrol_time_mm": p.get("patrol_time_mm"),
                "status": p.get("status") or "",
                "memo": p.get("memo") or "",
                "intervened": safe_int(p.get("intervened")) or 0,
                "door_opened": safe_int(p.get("door_opened")) or 0,
                "safety_checks": p.get("safety_checks") or "",
                "created_at": now,
            },
        )

    conn.commit()
    return record_id


def soft_delete_record(conn, record_id: int):
    exec_sql(
        conn,
        "UPDATE daily_records SET is_deleted=1, updated_at=:u WHERE id=:id",
        {"u": now_iso(), "id": int(record_id)},
    )


def mark_report_confirmed(conn, record_id: int):
    exec_sql(
        conn,
        "UPDATE daily_records SET is_confirmed=1, updated_at=:u WHERE id=:id",
        {"u": now_iso(), "id": int(record_id)},
    )


def list_records_for_day(conn, resident_id: int, target_date: str):
    return fetch_df(
        conn,
        """
        SELECT
            r.*,
            (SELECT COUNT(1) FROM daily_patrols p WHERE p.record_id=r.id) AS patrol_count
        FROM daily_records r
        WHERE r.resident_id=:resident_id
          AND r.record_date=:target_date
          AND r.is_deleted=0
        ORDER BY
          (r.record_time_hh IS NULL),
          r.record_time_hh ASC,
          r.record_time_mm ASC,
          r.id ASC
        """,
        {"resident_id": int(resident_id), "target_date": str(target_date)},
    )


def load_patrols(conn, record_id: int):
    return fetch_df(
        conn,
        """
        SELECT patrol_no, patrol_time_hh, patrol_time_mm, status, memo, intervened, door_opened, safety_checks
          FROM daily_patrols
         WHERE record_id=:rid
         ORDER BY patrol_no ASC
        """,
        {"rid": int(record_id)},
    )


def list_reports_for_day(conn, unit_id: int, target_date: str):
    return fetch_df(
        conn,
        """
        SELECT r.id, r.resident_id, rs.name AS resident_name,
               r.record_time_hh, r.record_time_mm, r.scene, r.scene_note, r.note,
               r.shift, r.recorder_name, r.is_confirmed
          FROM daily_records r
          JOIN residents rs ON rs.id = r.resident_id
         WHERE r.unit_id=:uid
           AND r.record_date=:d
           AND r.is_deleted=0
           AND r.is_report=1
         ORDER BY
           (r.record_time_hh IS NULL),
           r.record_time_hh ASC, r.record_time_mm ASC, r.id ASC
        """,
        {"uid": int(unit_id), "d": str(target_date)},
    )


# -------------------------
# CSS
# -------------------------
def inject_css():
    st.markdown(
        """
<style>
:root{
  --bg:#f5f6f8;
  --card:#ffffff;
  --text:#111827;
  --muted:#6b7280;
  --border:rgba(17,24,39,0.10);
  --accent:#0f766e;
  --danger:#e11d48;
  --warn:#f59e0b;
  --shadow2: 0 2px 10px rgba(17,24,39,0.06);
}
.stApp { background: var(--bg); color: var(--text); }
.block-container { padding-top: 1.1rem; padding-bottom: 2.5rem; }

.record-card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: var(--shadow2);
  margin: 10px 0 14px 0;
}

.record-alert{
  border-color: rgba(225,29,72,0.35);
  background: rgba(225,29,72,0.03);
}
.record-alert .meta,
.record-alert .vital-line,
.record-alert .note-box{
  color: var(--danger) !important;
}

.section-title{
  font-size: 16px;
  font-weight: 900;
  margin: 0 0 8px 0;
  padding-left: 12px;
  border-left: 6px solid var(--accent);
  line-height: 1.2;
}
.section-sub{
  color: var(--muted);
  font-size: 12px;
  margin-top: -4px;
  margin-bottom: 10px;
}

.badge{
  display:inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(17,24,39,0.03);
  font-size: 12px;
  font-weight: 800;
  margin-left: 6px;
}
.badge-ok{ background: rgba(16,185,129,0.12); border-color: rgba(16,185,129,0.25); }
.badge-danger{ background: rgba(225,29,72,0.12); border-color: rgba(225,29,72,0.28); color: var(--danger); }

.meta{ color: rgba(17,24,39,0.60); font-size: 12px; font-weight: 800; }
.vital-line{ font-size: 12.5px; color: rgba(17,24,39,0.86); margin-top: 6px; }
.note-box{ margin-top: 8px; font-size: 13px; line-height: 1.45; white-space: pre-wrap; }

.big-save .stButton > button{
  width:100% !important;
  border-radius: 14px !important;
  padding: 0.75rem 1rem !important;
  font-weight: 900 !important;
  font-size: 1.02rem !important;
  background: var(--accent) !important;
  border: 1px solid rgba(0,0,0,0.05) !important;
  color: white !important;
}

.report-board{
  background: #fff7cc;
  border: 1px solid rgba(245,158,11,0.35);
  border-radius: 16px;
  padding: 12px 14px;
  box-shadow: var(--shadow2);
}
</style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------
# main page (daily)
# -------------------------
def page_daily(conn):
    maybe_toast()
    ensure_epochs()

    st.sidebar.title("📌 条件")
    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット", units_df["name"].tolist(), index=0, key="d_unit")
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    target_date = st.sidebar.date_input("日付", value=date.today(), key="d_date")
    target_date_str = target_date.isoformat()

    st.sidebar.divider()
    shift = st.sidebar.radio("勤務区分", ["日勤", "夜勤"], index=0, key="d_shift")
    recorder_name = st.sidebar.text_input("記録者名（必須）", value=st.session_state.get("recorder_name", ""), key="d_recorder")
    st.session_state["recorder_name"] = recorder_name

    st.title("📝 介護記録（監査対応 / 時系列保持）")
    st.caption(f"DB: {DB_PATH}")

    residents_df = fetch_df(
        conn,
        "SELECT id, name FROM residents WHERE unit_id=:uid AND is_active=1 ORDER BY name;",
        {"uid": unit_id},
    )

    if "selected_resident_id" not in st.session_state:
        st.session_state["selected_resident_id"] = None

    st.subheader("👥 利用者")
    cols = st.columns(3)
    for idx, row in residents_df.iterrows():
        rid = int(row["id"])
        nm = str(row["name"])
        c = cols[idx % 3]
        with c:
            st.markdown(
                f"""
<div class="record-card">
  <div class="section-title">{esc(nm)}</div>
  <div class="section-sub">この日の記録を入力・確認</div>
</div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("開く", key=f"open_{rid}", use_container_width=True):
                st.session_state["selected_resident_id"] = rid
                st.session_state[ADD_EPOCH_KEY] = int(st.session_state[ADD_EPOCH_KEY]) + 1
                st.rerun()

    st.divider()

    selected = st.session_state.get("selected_resident_id")
    if selected is None:
        st.info("上の一覧から利用者を選択してください。")
        return

    sel_name = str(residents_df.loc[residents_df["id"] == selected, "name"].iloc[0])

    tcol, bcol = st.columns([7, 3])
    with tcol:
        st.subheader(f"✍️ 入力 / 一覧：{sel_name} 様（{target_date_str}）")
    with bcol:
        st.markdown('<div class="big-save">', unsafe_allow_html=True)
        top_save_clicked = st.button("保存して記録を追加", key="top_save_btn", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    hh_options = ["未選択"] + list(range(0, 24))
    mm_options = ["未選択"] + list(range(0, 60, 5))

    # ① 支援記録（スマホ最適化）
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">① 支援記録（時刻・場面）</div>', unsafe_allow_html=True)

        # ✅ columns比率：指定通り
        c1, c2, c3, c4, c5 = st.columns([1, 1.2, 2, 4, 1.8])

        with c1:
            add_hh = st.selectbox(
                "時",
                hh_options,
                index=0,
                key=wkey("add_time_hh"),
            )

        with c2:
            # ✅ ラベルが長くて改行される問題を潰す：label_visibility="collapsed"
            add_mm = st.selectbox(
                "分",
                mm_options,
                index=0,
                key=wkey("add_time_mm"),
                label_visibility="collapsed",
            )
            # ただし collapsed だと何の欄かわからないので、極小キャプションで補助
            st.caption("分")

        with c3:
            add_scene = st.selectbox(
                "場面",
                SCENES,
                index=SCENES.index("ご様子"),
                format_func=scene_display,
                key=wkey("add_scene"),
            )

        with c4:
            scene_note = st.text_input(
                "内容（短文）",
                value="",
                key=wkey("scene_note"),
                placeholder="例：声かけで落ち着く／不穏あり等",
                disabled=(add_scene == ""),
            )

        with c5:
            is_report = st.checkbox("重要：申し送り", value=False, key=wkey("is_report"))

        st.markdown("</div>", unsafe_allow_html=True)

    # ⑥ 特記事項
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⑥ 特記事項</div>', unsafe_allow_html=True)

        note = st.text_area(
            "特記事項（詳細）",
            value="",
            height=220,
            key=wkey("note"),
            placeholder="例：いつもと違う行動／不穏／対応／結果／引き継ぎ事項 など",
        )

        st.markdown('<div class="big-save">', unsafe_allow_html=True)
        bottom_save_clicked = st.button("保存して記録を追加", key="bottom_save_btn", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # 保存（最小構成版：①＋⑥のみにしてあります）
    save_clicked = top_save_clicked or bottom_save_clicked
    if save_clicked:
        if recorder_name.strip() == "":
            st.error("記録者名（必須）を入力してください。")
        else:
            chosen_hh = None if add_hh == "未選択" else safe_int(add_hh)
            chosen_mm = None if add_mm == "未選択" else safe_int(add_mm)
            if chosen_hh is None or chosen_mm is None:
                st.error("時刻（時/分）を入力してください。")
            else:
                payload = {
                    "unit_id": unit_id,
                    "resident_id": int(selected),
                    "record_date": target_date_str,
                    "record_time_hh": chosen_hh,
                    "record_time_mm": chosen_mm,
                    "shift": shift,
                    "recorder_name": recorder_name.strip(),
                    "scene": add_scene if add_scene in SCENES else "",
                    "scene_note": (scene_note or "").strip(),
                    "note": (note or "").strip(),
                    "is_report": 1 if is_report else 0,
                    "is_confirmed": 0,
                }
                record_id = insert_record(conn, payload, patrols=[])
                bump_add_epoch_and_rerun(f"✅ 記録を保存しました（ID: {record_id}）")

    st.divider()

    # 申し送りボード
    st.markdown("### 📋 シフト申し送りボード（コピー用）")
    rep_df = list_reports_for_day(conn, unit_id, target_date_str)

    st.markdown('<div class="report-board">', unsafe_allow_html=True)
    if rep_df.empty:
        st.write("申し送り対象（重要チェックON）の記録はありません。")
        copy_text = ""
    else:
        lines = []
        for _, rr in rep_df.iterrows():
            rid_rec = int(rr["id"])
            t = hhmm(rr.get("record_time_hh"), rr.get("record_time_mm"))
            resident_name = str(rr.get("resident_name") or "")
            scene = scene_display(rr.get("scene"))
            recorder = str(rr.get("recorder_name") or "")
            sn = (str(rr.get("scene_note") or "")).strip()
            nt = (str(rr.get("note") or "")).strip()

            msg = f"{t} {resident_name} / {scene} / {recorder}"
            if sn:
                msg += f" / 短文:{sn}"
            if nt:
                msg += f" / 特記事項:{nt}"
            lines.append(msg)

            cL, cR = st.columns([8, 2])
            with cL:
                confirmed = (safe_int(rr.get("is_confirmed")) == 1)
                st.write(("✅ 確認済み " if confirmed else "• ") + msg)
            with cR:
                confirmed = (safe_int(rr.get("is_confirmed")) == 1)
                if confirmed:
                    st.write("✅確認済")
                else:
                    if st.button("確認しました", key=f"conf_{rid_rec}", use_container_width=True):
                        mark_report_confirmed(conn, rid_rec)
                        st.session_state["__toast__"] = "✅ 申し送りを確認済みにしました"
                        st.rerun()

        copy_text = "\n".join(lines)

    st.text_area("コピー（そのまま貼り付けできます）", value=copy_text, height=140)
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # 履歴（特記事項は赤）
    st.markdown("### 📋 支援記録一覧（履歴 / 削除）")
    recs = list_records_for_day(conn, selected, target_date_str)
    if recs.empty:
        st.info("この日の記録はまだありません。")
        return

    scroll = st.container(height=600)
    with scroll:
        for _, r in recs.iterrows():
            rec_id = int(r["id"])
            t = hhmm(r.get("record_time_hh"), r.get("record_time_mm"))
            note_txt = (str(r.get("note") or "")).strip()
            has_note = (note_txt != "")

            badges = []
            if safe_int(r.get("is_report")) == 1:
                badges.append("📋申し送り")
            if has_note:
                badges.append("要確認")

            card_class = "record-card record-alert" if has_note else "record-card"
            st.markdown(f"<div class='{card_class}'>", unsafe_allow_html=True)

            h1, h2 = st.columns([8, 2])
            with h1:
                b_html = ""
                if badges:
                    b_html = " ".join(
                        [
                            f"<span class='badge badge-danger'>{esc(x)}</span>" if x == "要確認"
                            else f"<span class='badge badge-ok'>{esc(x)}</span>"
                            for x in badges
                        ]
                    )

                title = f"{t} / {scene_display(r.get('scene'))} / 記録者：{r.get('recorder_name')}"
                st.markdown(f"<div class='meta'><b>{esc(title)}</b> {b_html}</div>", unsafe_allow_html=True)

            with h2:
                if st.button("🗑️ 削除", key=f"del_{rec_id}", use_container_width=True):
                    soft_delete_record(conn, rec_id)
                    st.session_state["__toast__"] = "🗑️ 記録を削除（論理削除）しました"
                    st.rerun()

            sn = (str(r.get("scene_note") or "")).strip()
            if sn:
                st.markdown(f"<div class='vital-line'>■ 短文：{to_html_lines(sn)}</div>", unsafe_allow_html=True)

            if has_note:
                st.markdown(
                    f"<div class='note-box'><b>■ 特記事項：</b><br>{to_html_lines(note_txt)}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("</div>", unsafe_allow_html=True)


# -------------------------
# main
# -------------------------
def main():
    st.set_page_config(page_title="介護記録（監査対応）", layout="wide")
    inject_css()

    conn = get_conn()
    init_db(conn)

    page_daily(conn)

    conn.close()


if __name__ == "__main__":
    main()
