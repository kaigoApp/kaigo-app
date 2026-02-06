# app.py
# ============================================================
# グループホーム向け 介護記録アプリ（Streamlit + SQLite）
#
# ✅ 追加反映（2026-02）
# 1) 画面レイアウト
#    - メインタイトル（介護記録）を一回り小さくスマートに
#    - 保存ボタンを「タイトル右」と「⑥ 特記事項の直下」に2箇所配置
#
# 2) 動的バリデーション（視覚効果）
#    - ⑥ 特記事項に入力がある間、① 支援記録タイトルを赤で強調
#
# 3) バイタル初期値の改善
#    - 0初期値を廃止
#    - 直近の記録値があれば引き継ぎ、なければ標準値（例: 36.5 / 120 / 80 ...）
#    - 「未測定」トグルで未入力（NULL保存）も可能
#
# 4) 職員用「申し送り（連絡帳）」機能
#    - 専用タブ追加（記録とは別）
#    - ⑥ 特記事項がある場合、保存時に申し送りへ自動コピー
#    - リアクション（確認✅）と「誰が確認したか」を可視化
#
# インストール:
#   py -m pip install streamlit pandas
# 起動:
#   py -m streamlit run app.py
# ============================================================

import sqlite3
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import streamlit as st


# -------------------------
# Paths
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "tomogaki_proto.db"


# -------------------------
# DB helpers
# -------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def fetch_df(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def exec_sql(conn, sql, params=()):
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

    # --- residents extra fields ---
    ensure_column(conn, "residents", "kubun", "kubun TEXT")
    ensure_column(conn, "residents", "disease", "disease TEXT")

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

    # --- vitals ---
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

    # --- added fields ---
    ensure_column(conn, "daily_records", "scene_note", "scene_note TEXT")
    ensure_column(conn, "daily_records", "wakeup_flag", "wakeup_flag INTEGER NOT NULL DEFAULT 0")

    # -------------------------
    # 申し送り（連絡帳）
    # -------------------------
    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS handovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL,
            resident_id INTEGER,
            handover_date TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by TEXT NOT NULL,
            source_record_id INTEGER,
            created_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE,
            FOREIGN KEY(resident_id) REFERENCES residents(id) ON DELETE SET NULL,
            FOREIGN KEY(source_record_id) REFERENCES daily_records(id) ON DELETE SET NULL
        );
        """,
    )
    exec_sql(
        conn,
        """
        CREATE TABLE IF NOT EXISTS handover_reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handover_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            reaction_type TEXT NOT NULL, -- 'check' or 'like'
            created_at TEXT NOT NULL,
            UNIQUE(handover_id, user_name, reaction_type),
            FOREIGN KEY(handover_id) REFERENCES handovers(id) ON DELETE CASCADE
        );
        """,
    )
    # 連携重複防止（ある場合だけ追加）
    try:
        exec_sql(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_handovers_src ON handovers(source_record_id);")
    except Exception:
        pass

    # seed
    units = fetch_df(conn, "SELECT id FROM units LIMIT 1;")
    if units.empty:
        exec_sql(conn, "INSERT INTO units(name) VALUES (?)", ("ユニットA",))
        exec_sql(conn, "INSERT INTO units(name) VALUES (?)", ("ユニットB",))

    res = fetch_df(conn, "SELECT id FROM residents LIMIT 1;")
    if res.empty:
        u = fetch_df(conn, "SELECT id, name FROM units ORDER BY id;")
        unit_a = int(u.loc[0, "id"])
        unit_b = int(u.loc[1, "id"]) if len(u) > 1 else unit_a
        for nm in ["佐藤 太郎", "鈴木 花子", "田中 次郎", "山田 恒一"]:
            exec_sql(conn, "INSERT INTO residents(unit_id, name) VALUES(?,?)", (unit_a, nm))
        for nm in ["高橋 美咲", "伊藤 恒一"]:
            exec_sql(conn, "INSERT INTO residents(unit_id, name) VALUES(?,?)", (unit_b, nm))


# -------------------------
# AI stub
# -------------------------
def generate_ai_care_suggestions(conn, unit_id: int, target_date: str):
    return "（AI支援案）※将来OpenAI APIで実装します。現状は枠だけです。"


# -------------------------
# UI helpers
# -------------------------
SCENES = ["", "起床", "ご様子", "食事", "入浴", "就寝前", "外出", "通所", "服薬", "対人", "金銭", "その他"]
SCENE_LABEL = {"": "未選択"}


def scene_display(s: str) -> str:
    if s is None:
        return "未選択"
    s = str(s)
    return SCENE_LABEL.get(s, s)


def safe_int(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return int(x)
    except Exception:
        return None


def safe_float(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except Exception:
        return None


def fmt_dt(s):
    if not s:
        return "--"
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
            return dt.strftime("%Y-%m-%d %H:%M")
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(s)


def fmt_time(hh, mm) -> str:
    if hh is None or mm is None:
        return "時刻なし"
    return f"{int(hh):02d}:{int(mm):02d}"


def get_latest_for_resident(conn, resident_id: int, target_date: str):
    df = fetch_df(
        conn,
        """
        SELECT r.*,
               (SELECT COUNT(1) FROM daily_patrols p WHERE p.record_id=r.id) AS patrol_count
          FROM daily_records r
         WHERE r.resident_id=?
           AND r.record_date=?
           AND r.is_deleted=0
         ORDER BY r.updated_at DESC, r.id DESC
         LIMIT 1
        """,
        (resident_id, target_date),
    )
    if df.empty:
        return None
    return df.loc[0]


def get_latest_vitals_anyday(conn, resident_id: int):
    """
    直近の記録（どの日付でも）から、バイタル初期値の候補を取る。
    """
    df = fetch_df(
        conn,
        """
        SELECT temp_am, bp_sys_am, bp_dia_am, pulse_am, spo2_am,
               temp_pm, bp_sys_pm, bp_dia_pm, pulse_pm, spo2_pm
          FROM daily_records
         WHERE resident_id=? AND is_deleted=0
         ORDER BY record_date DESC, updated_at DESC, id DESC
         LIMIT 1
        """,
        (resident_id,),
    )
    if df.empty:
        return {}
    row = df.loc[0].to_dict()
    # NULLはそのまま
    return row


def list_records_for_day(conn, resident_id: int, target_date: str):
    return fetch_df(
        conn,
        """
        SELECT r.id,
               r.record_time_hh,
               r.record_time_mm,
               r.shift,
               r.recorder_name,
               r.scene,
               r.scene_note,

               r.temp_am, r.spo2_am, r.pulse_am, r.bp_sys_am, r.bp_dia_am,
               r.temp_pm, r.spo2_pm, r.pulse_pm, r.bp_sys_pm, r.bp_dia_pm,

               r.meal_bf_done, r.meal_bf_score,
               r.meal_lu_done, r.meal_lu_score,
               r.meal_di_done, r.meal_di_score,

               r.med_morning, r.med_noon, r.med_evening, r.med_bed,

               r.note,
               substr(r.note,1,120) AS note_head,

               r.created_at,
               r.updated_at,

               (SELECT COUNT(1) FROM daily_patrols p WHERE p.record_id=r.id) AS patrol_count
          FROM daily_records r
         WHERE r.resident_id=?
           AND r.record_date=?
           AND r.is_deleted=0
         ORDER BY
           (r.record_time_hh IS NULL) ASC,
           r.record_time_hh ASC,
           r.record_time_mm ASC,
           r.id ASC
        """,
        (resident_id, target_date),
    )


def load_patrols(conn, record_id: int):
    return fetch_df(
        conn,
        """
        SELECT patrol_no, patrol_time_hh, patrol_time_mm, status, memo, intervened, door_opened, safety_checks
          FROM daily_patrols
         WHERE record_id=?
         ORDER BY patrol_no
        """,
        (record_id,),
    )


def upsert_record(conn, payload: dict, patrols: list):
    cur = conn.cursor()
    now = now_iso()

    if payload.get("id") is None:
        cur.execute(
            """
            INSERT INTO daily_records(
                unit_id, resident_id,
                record_date, record_time_hh, record_time_mm,
                shift, recorder_name, scene, scene_note, wakeup_flag,

                temp_am, bp_sys_am, bp_dia_am, pulse_am, spo2_am,
                temp_pm, bp_sys_pm, bp_dia_pm, pulse_pm, spo2_pm,

                meal_bf_done, meal_bf_score,
                meal_lu_done, meal_lu_score,
                meal_di_done, meal_di_score,

                med_morning, med_noon, med_evening, med_bed,
                note, is_deleted, created_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["unit_id"], payload["resident_id"],
                payload["record_date"], payload["record_time_hh"], payload["record_time_mm"],
                payload["shift"], payload["recorder_name"], payload["scene"], payload["scene_note"], payload["wakeup_flag"],

                payload["temp_am"], payload["bp_sys_am"], payload["bp_dia_am"], payload["pulse_am"], payload["spo2_am"],
                payload["temp_pm"], payload["bp_sys_pm"], payload["bp_dia_pm"], payload["pulse_pm"], payload["spo2_pm"],

                payload["meal_bf_done"], payload["meal_bf_score"],
                payload["meal_lu_done"], payload["meal_lu_score"],
                payload["meal_di_done"], payload["meal_di_score"],

                payload["med_morning"], payload["med_noon"], payload["med_evening"], payload["med_bed"],
                payload["note"], 0, now, now,
            ),
        )
        record_id = int(cur.lastrowid)
    else:
        record_id = int(payload["id"])
        cur.execute(
            """
            UPDATE daily_records
               SET record_time_hh=?,
                   record_time_mm=?,
                   shift=?,
                   recorder_name=?,
                   scene=?,
                   scene_note=?,
                   wakeup_flag=?,

                   temp_am=?, bp_sys_am=?, bp_dia_am=?, pulse_am=?, spo2_am=?,
                   temp_pm=?, bp_sys_pm=?, bp_dia_pm=?, pulse_pm=?, spo2_pm=?,

                   meal_bf_done=?, meal_bf_score=?,
                   meal_lu_done=?, meal_lu_score=?,
                   meal_di_done=?, meal_di_score=?,

                   med_morning=?, med_noon=?, med_evening=?, med_bed=?,
                   note=?,
                   updated_at=?
             WHERE id=?
            """,
            (
                payload["record_time_hh"], payload["record_time_mm"],
                payload["shift"], payload["recorder_name"], payload["scene"],
                payload["scene_note"], payload["wakeup_flag"],

                payload["temp_am"], payload["bp_sys_am"], payload["bp_dia_am"], payload["pulse_am"], payload["spo2_am"],
                payload["temp_pm"], payload["bp_sys_pm"], payload["bp_dia_pm"], payload["pulse_pm"], payload["spo2_pm"],

                payload["meal_bf_done"], payload["meal_bf_score"],
                payload["meal_lu_done"], payload["meal_lu_score"],
                payload["meal_di_done"], payload["meal_di_score"],

                payload["med_morning"], payload["med_noon"], payload["med_evening"], payload["med_bed"],
                payload["note"], now, record_id,
            ),
        )
        cur.execute("DELETE FROM daily_patrols WHERE record_id=?", (record_id,))

    for p in patrols:
        cur.execute(
            """
            INSERT INTO daily_patrols(
                record_id, patrol_no, patrol_time_hh, patrol_time_mm,
                status, memo, intervened, door_opened, safety_checks, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record_id,
                int(p.get("patrol_no")),
                p.get("patrol_time_hh"),
                p.get("patrol_time_mm"),
                p.get("status") or "",
                p.get("memo") or "",
                int(p.get("intervened", 0)),
                int(p.get("door_opened", 0)),
                p.get("safety_checks") or "",
                now,
            ),
        )

    conn.commit()
    return record_id


def soft_delete_record(conn, record_id: int):
    exec_sql(conn, "UPDATE daily_records SET is_deleted=1, updated_at=? WHERE id=?", (now_iso(), int(record_id)))


# -------------------------
# Handover (申し送り)
# -------------------------
def add_handover_from_note(conn, *, unit_id: int, resident_id: int | None, handover_date: str, content: str, created_by: str, source_record_id: int | None):
    content = (content or "").strip()
    if content == "":
        return None
    now = now_iso()
    # source_record_idがある場合は一意（idx_handovers_src）なので、重複時はスキップ
    try:
        cur = exec_sql(
            conn,
            """
            INSERT INTO handovers(unit_id, resident_id, handover_date, content, created_by, source_record_id, created_at, is_deleted)
            VALUES(?,?,?,?,?,?,?,0)
            """,
            (unit_id, resident_id, handover_date, content, created_by, source_record_id, now),
        )
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def list_handovers(conn, *, unit_id: int, handover_date: str):
    return fetch_df(
        conn,
        """
        SELECT h.id, h.unit_id, h.resident_id, h.handover_date, h.content, h.created_by, h.created_at
          FROM handovers h
         WHERE h.unit_id=? AND h.handover_date=? AND h.is_deleted=0
         ORDER BY h.created_at DESC, h.id DESC
        """,
        (unit_id, handover_date),
    )


def list_reactions(conn, handover_id: int):
    return fetch_df(
        conn,
        """
        SELECT user_name, reaction_type, created_at
          FROM handover_reactions
         WHERE handover_id=?
         ORDER BY created_at ASC, id ASC
        """,
        (handover_id,),
    )


def has_reaction(conn, *, handover_id: int, user_name: str, reaction_type: str) -> bool:
    df = fetch_df(
        conn,
        "SELECT 1 FROM handover_reactions WHERE handover_id=? AND user_name=? AND reaction_type=? LIMIT 1",
        (handover_id, user_name, reaction_type),
    )
    return not df.empty


def toggle_reaction(conn, *, handover_id: int, user_name: str, reaction_type: str):
    now = now_iso()
    if has_reaction(conn, handover_id=handover_id, user_name=user_name, reaction_type=reaction_type):
        exec_sql(
            conn,
            "DELETE FROM handover_reactions WHERE handover_id=? AND user_name=? AND reaction_type=?",
            (handover_id, user_name, reaction_type),
        )
    else:
        exec_sql(
            conn,
            "INSERT OR IGNORE INTO handover_reactions(handover_id, user_name, reaction_type, created_at) VALUES(?,?,?,?)",
            (handover_id, user_name, reaction_type, now),
        )


# -------------------------
# Reset strategy (epoch方式)
# -------------------------
ADD_EPOCH_KEY = "__add_epoch__"
TOAST_SAVED_KEY = "__toast_saved__"


def ensure_epoch():
    if ADD_EPOCH_KEY not in st.session_state:
        st.session_state[ADD_EPOCH_KEY] = 0


def add_key(name: str) -> str:
    epoch = st.session_state.get(ADD_EPOCH_KEY, 0)
    return f"{name}__e{epoch}"


def bump_epoch_and_rerun():
    st.session_state[TOAST_SAVED_KEY] = True
    st.session_state[ADD_EPOCH_KEY] = int(st.session_state.get(ADD_EPOCH_KEY, 0)) + 1
    st.rerun()


def show_toast_if_needed():
    if st.session_state.get(TOAST_SAVED_KEY, False):
        try:
            st.toast("✅ 記録を保存しました")
        except Exception:
            st.success("✅ 記録を保存しました")
        st.session_state[TOAST_SAVED_KEY] = False


# -------------------------
# CSS (Clean Pro / Audit-ready)
# -------------------------
def inject_css():
    st.markdown(
        """
<style>
:root{
  --bg:#f4f6f9;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,0.10);
  --accent:#0f766e;
  --accent2:#2563eb;
  --danger:#ff1f1f; /* vivid red */
  --warn:#b45309;
  --ok:#047857;
  --shadow: 0 10px 30px rgba(15,23,42,0.08);
  --shadow2: 0 2px 12px rgba(15,23,42,0.06);
  --highlight-bg: rgba(253, 230, 138, 0.35);
  --highlight-border: rgba(245, 158, 11, 0.85);
}

.stApp { background: var(--bg); color: var(--text); }
.block-container { padding-top: 0.8rem; padding-bottom: 2.2rem; max-width: 760px; }

/* ---- Mobile first typography ---- */
html, body, [class*="css"]  { font-size: 16px; }
label, p, span, div { font-size: 16px; }
@media (min-width: 900px){
  .block-container{ max-width: 900px; }
}

/* title: do not truncate */
.app-title{
  font-size: 20px;
  font-weight: 1000;
  letter-spacing: .2px;
  margin: 0 0 8px 0;
  line-height: 1.25;
  white-space: normal;
  overflow-wrap: anywhere;
}
.app-title .muted{ color: rgba(15,23,42,0.70); font-weight: 900; }
.app-title.danger{ color: var(--danger); }

/* cards */
.record-card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 14px 14px 14px 14px;
  box-shadow: var(--shadow2);
  margin: 10px 0 14px 0;
}

.section-title{
  font-size: 16px;
  font-weight: 1000;
  margin: 0 0 10px 0;
  padding-left: 12px;
  border-left: 6px solid var(--accent);
  line-height: 1.2;
}
.section-title.danger{
  border-left-color: var(--danger);
  color: var(--danger);
  font-weight: 1000;
}
.section-sub{
  color: var(--muted);
  font-size: 12px;
  margin-top: -6px;
  margin-bottom: 10px;
}
.resident-meta{font-size:12px;color:rgba(15,23,42,0.68);margin-top:-6px;margin-bottom:10px;}

/* Make all buttons finger friendly */
.stButton > button{
  font-size: 16px !important;
  font-weight: 1000 !important;
  padding: 0.9rem 1.0rem !important;
  border-radius: 14px !important;
}

/* save buttons */
.top-save .stButton > button,
.bottom-save .stButton > button{
  width:100% !important;
  background: var(--accent2) !important;
  border: 1px solid rgba(0,0,0,0.05) !important;
  color: white !important;
  box-shadow: 0 14px 30px rgba(37,99,235,0.18);
}
.danger-save .stButton > button{
  width:100% !important;
  background: var(--danger) !important;
  border: 1px solid rgba(0,0,0,0.05) !important;
  color: white !important;
  box-shadow: 0 14px 30px rgba(255,31,31,0.20);
}

/* text areas */
textarea, input{
  font-size: 16px !important;
}
textarea{ border-radius: 14px !important; }

/* sidebar */
section[data-testid="stSidebar"]{
  border-right: 1px solid var(--border);
  background: #ffffff;
}

/* handover */
.handover-card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 14px 16px;
  box-shadow: var(--shadow2);
  margin: 10px 0 12px 0;
}
.handover-meta{
  font-size: 12px;
  color: rgba(15,23,42,0.72);
  margin-top: 6px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------
# Card rendering helpers
# -------------------------
def vital_html(label: str, value: str, alert: bool = False) -> str:
    cls = "vital-pill vital-alert" if alert else "vital-pill"
    return f"<span class='{cls}'><span class='vital-label'>{label}</span><span class='vital-value'>{value}</span></span>"


def build_vital_section(r) -> str:
    """
    ✅ 未入力(0/NULL)は“0表示しない”
    - 値があるものだけ表示
    - 血圧は片方欠けても '--'、両方未入力なら非表示
    """
    def nz_int(v):
        v = safe_int(v)
        if v is None:
            return None
        return None if int(v) == 0 else int(v)

    def nz_float(v):
        v = safe_float(v)
        if v is None:
            return None
        return None if float(v) == 0.0 else float(v)

    parts = []

    t_am = nz_float(r.get("temp_am"))
    sys_am = nz_int(r.get("bp_sys_am"))
    dia_am = nz_int(r.get("bp_dia_am"))
    pulse_am = nz_int(r.get("pulse_am"))
    spo2_am = nz_int(r.get("spo2_am"))

    t_pm = nz_float(r.get("temp_pm"))
    sys_pm = nz_int(r.get("bp_sys_pm"))
    dia_pm = nz_int(r.get("bp_dia_pm"))
    pulse_pm = nz_int(r.get("pulse_pm"))
    spo2_pm = nz_int(r.get("spo2_pm"))

    if t_am is not None:
        parts.append(vital_html("朝 体温", f"{t_am:.1f}℃", alert=(t_am >= 37.5)))
    if sys_am is not None or dia_am is not None:
        v = f"{sys_am if sys_am is not None else '--'}/{dia_am if dia_am is not None else '--'}"
        parts.append(vital_html("朝 血圧", v))
    if pulse_am is not None:
        parts.append(vital_html("朝 脈拍", f"{pulse_am}"))
    if spo2_am is not None:
        parts.append(vital_html("朝 SpO₂", f"{spo2_am}%"))

    if t_pm is not None:
        parts.append(vital_html("夕 体温", f"{t_pm:.1f}℃", alert=(t_pm >= 37.5)))
    if sys_pm is not None or dia_pm is not None:
        v = f"{sys_pm if sys_pm is not None else '--'}/{dia_pm if dia_pm is not None else '--'}"
        parts.append(vital_html("夕 血圧", v))
    if pulse_pm is not None:
        parts.append(vital_html("夕 脈拍", f"{pulse_pm}"))
    if spo2_pm is not None:
        parts.append(vital_html("夕 SpO₂", f"{spo2_pm}%"))

    if not parts:
        return ""

    return "<div class='vital-grid'>" + "".join(parts) + "</div>"


def build_patrol_inline(conn, record_id: int) -> str:
    pat_df = load_patrols(conn, record_id)
    if pat_df.empty:
        return ""

    safety_options = ["室温OK", "体調変化なし", "危険物なし", "転倒リスクなし"]
    rows = []
    for _, p in pat_df.iterrows():
        no = safe_int(p.get("patrol_no")) or 0
        ph = p.get("patrol_time_hh")
        pm = p.get("patrol_time_mm")
        pt = fmt_time(ph, pm) if (pd.notna(ph) and pd.notna(pm)) else "時刻なし"
        status = (p.get("status") or "").strip()
        memo = (p.get("memo") or "").strip()
        intervened = bool(safe_int(p.get("intervened")) or 0)
        door = bool(safe_int(p.get("door_opened")) or 0)
        safety = (p.get("safety_checks") or "").strip()
        safety_list = [x for x in safety.split(",") if x.strip()] if safety else []
        safety_list = [x for x in safety_list if x in safety_options] + [x for x in safety_list if x not in safety_options]

        bits = []
        if status:
            bits.append(f"状況：{status}")
        if safety_list:
            bits.append(f"安全：{' / '.join(safety_list)}")
        if intervened:
            bits.append("対応あり")
        if door:
            bits.append("ドア開放")
        if memo:
            bits.append(f"メモ：{memo}")

        detail = " ｜ ".join(bits) if bits else "（内容なし）"
        rows.append(f"<div class='patrol-item'>・巡視{no}（{pt}）<span class='patrol-sub'>　{detail}</span></div>")

    return (
        "<div class='patrol-box'>"
        "<div class='patrol-title'>✅ 巡視記録</div>"
        + "".join(rows)
        + "</div>"
    )


# -------------------------
# main
# -------------------------
def main():
    # Mobile-first: centered layout
    st.set_page_config(page_title="介護記録", layout="centered")
    inject_css()
    ensure_epoch()

    conn = get_conn()
    init_db(conn)

    # ---- Sidebar (PC向け。スマホでは折りたたまれる想定) ----
    st.sidebar.title("📌 条件")
    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット", units_df["name"].tolist(), index=0)
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    target_date = st.sidebar.date_input("日付", value=date.today())
    target_date_str = target_date.isoformat()

    shift = st.sidebar.radio("勤務区分", ["日勤", "夜勤"], index=0)

    st.sidebar.divider()
    recorder_name = st.sidebar.text_input("✍️ 記録者名（必須 / 申し送りの表示名）", value=st.session_state.get("recorder_name", ""))
    st.session_state["recorder_name"] = recorder_name

    st.sidebar.divider()
    if st.sidebar.button("🤖 AI支援案（準備枠）", use_container_width=True):
        st.sidebar.success(generate_ai_care_suggestions(conn, unit_id, target_date_str))

    show_toast_if_needed()

    # ---- data ----
    residents_df = fetch_df(
        conn,
        "SELECT id, name, kubun, disease FROM residents WHERE unit_id=? AND is_active=1 ORDER BY name;",
        (unit_id,),
    )
    if residents_df.empty:
        st.info("このユニットに利用者が登録されていません。")
        conn.close()
        return

    if "selected_resident_id" not in st.session_state or st.session_state["selected_resident_id"] is None:
        st.session_state["selected_resident_id"] = int(residents_df.iloc[0]["id"])

    # ---- Tabs (入力 / 経過一覧 / 申し送り) ----
    tab_in, tab_list, tab_ho = st.tabs(["✍️ 入力", "📋 経過一覧", "🗒️ 申し送り"])

    # ======================================================================
    # 入力 TAB
    # ======================================================================
    with tab_in:
        # resident selector (1-column)
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        sel_name_list = residents_df["name"].tolist()
        sel_idx = sel_name_list.index(residents_df.loc[residents_df["id"] == st.session_state["selected_resident_id"], "name"].iloc[0])
        sel_name = st.selectbox("利用者", sel_name_list, index=sel_idx, key="resident_selectbox")
        selected = int(residents_df.loc[residents_df["name"] == sel_name, "id"].iloc[0])
        st.session_state["selected_resident_id"] = selected

        sel_row = residents_df.loc[residents_df["id"] == selected].iloc[0]
        sel_kubun = str(sel_row.get("kubun") or "-").strip() or "-"
        sel_disease = str(sel_row.get("disease") or "-").strip() or "-"
        st.markdown(f"<div class='resident-meta'>区分：{sel_kubun} / 病名：{sel_disease}</div>", unsafe_allow_html=True)

        # special preview (any char in note OR checkbox on)
        note_preview = (st.session_state.get(add_key("add_note"), "") or "").strip()
        special_flag_preview = bool(st.session_state.get(add_key("special_flag"), False))
        is_special_typing = special_flag_preview or (len(note_preview) > 0)

        # title (red when special)
        title_cls = "app-title danger" if is_special_typing else "app-title"
        st.markdown(f'<div class="{title_cls}">🧾 介護記録 <span class="muted">（Mobile First）</span></div>', unsafe_allow_html=True)

        # top save button (red when special)
        st.markdown(f"<div class='{ 'danger-save' if is_special_typing else 'top-save' }'>", unsafe_allow_html=True)
        save_clicked_top = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("top_save_btn"))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # helpers
        hh_options = ["未選択"] + list(range(0, 24))
        mm_options = ["未選択"] + list(range(0, 60, 5))
        safety_options = ["室温OK", "体調変化なし", "危険物なし", "転倒リスクなし"]
        patrol_status_options = ["", "就寝中（静か）", "起きている（静か）", "起きている（落ち着かない）", "不穏", "不在"]

        # Prefill vitals
        latest_v = get_latest_vitals_anyday(conn, selected)
        std = {
            "temp_am": 36.5, "bp_sys_am": 120, "bp_dia_am": 80, "pulse_am": 70, "spo2_am": 98,
            "temp_pm": 36.5, "bp_sys_pm": 120, "bp_dia_pm": 80, "pulse_pm": 70, "spo2_pm": 98,
        }
        def dv(key, as_type):
            v = latest_v.get(key)
            v = safe_float(v) if as_type == "float" else safe_int(v)
            if v is None:
                return std[key]
            return float(v) if as_type == "float" else int(v)

        # ---------------- ⑤ 巡視（先に） ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⑤ 巡視</div>', unsafe_allow_html=True)
        enable_patrol = st.checkbox("巡視を記録する", value=False, key=add_key("add_enable_patrol"))

        patrol_list = []
        patrol_main_time = None  # (hh,mm)
        def _try_time(hh, mm):
            if hh == "未選択" or mm == "未選択":
                return None
            try:
                return (int(hh), int(mm))
            except Exception:
                return None

        if enable_patrol:
            st.markdown("**巡視1**")
            p1_hh = st.selectbox("巡視1：時", hh_options, index=0, key=add_key("p1_hh"))
            p1_mm = st.selectbox("巡視1：分", mm_options, index=0, key=add_key("p1_mm"))
            p1_status = st.selectbox("巡視1：状況", patrol_status_options, index=0, key=add_key("p1_status"))
            p1_memo = st.text_input("巡視1：メモ", value="", key=add_key("p1_memo"))
            p1_int = st.checkbox("巡視1：対応した", value=False, key=add_key("p1_int"))
            p1_door = st.checkbox("巡視1：居室ドアを開けた", value=False, key=add_key("p1_door"))
            p1_safety = st.multiselect("巡視1：安全チェック", safety_options, default=[], key=add_key("p1_safety"))

            st.divider()
            st.markdown("**巡視2（任意）**")
            p2_hh = st.selectbox("巡視2：時", hh_options, index=0, key=add_key("p2_hh"))
            p2_mm = st.selectbox("巡視2：分", mm_options, index=0, key=add_key("p2_mm"))
            p2_status = st.selectbox("巡視2：状況", patrol_status_options, index=0, key=add_key("p2_status"))
            p2_memo = st.text_input("巡視2：メモ", value="", key=add_key("p2_memo"))
            p2_int = st.checkbox("巡視2：対応した", value=False, key=add_key("p2_int"))
            p2_door = st.checkbox("巡視2：居室ドアを開けた", value=False, key=add_key("p2_door"))
            p2_safety = st.multiselect("巡視2：安全チェック", safety_options, default=[], key=add_key("p2_safety"))

            def has_any(hh, mm, status, memo, intervened, door, safety):
                return (
                    (hh != "未選択" and mm != "未選択")
                    or (status or "").strip() != ""
                    or (memo or "").strip() != ""
                    or bool(intervened)
                    or bool(door)
                    or (len(safety or []) > 0)
                )

            if has_any(p1_hh, p1_mm, p1_status, p1_memo, p1_int, p1_door, p1_safety):
                patrol_list.append(
                    {
                        "patrol_no": 1,
                        "patrol_time_hh": None if p1_hh == "未選択" else int(p1_hh),
                        "patrol_time_mm": None if p1_mm == "未選択" else int(p1_mm),
                        "status": p1_status,
                        "memo": p1_memo,
                        "intervened": 1 if p1_int else 0,
                        "door_opened": 1 if p1_door else 0,
                        "safety_checks": ",".join(p1_safety),
                    }
                )
            if has_any(p2_hh, p2_mm, p2_status, p2_memo, p2_int, p2_door, p2_safety):
                patrol_list.append(
                    {
                        "patrol_no": 2,
                        "patrol_time_hh": None if p2_hh == "未選択" else int(p2_hh),
                        "patrol_time_mm": None if p2_mm == "未選択" else int(p2_mm),
                        "status": p2_status,
                        "memo": p2_memo,
                        "intervened": 1 if p2_int else 0,
                        "door_opened": 1 if p2_door else 0,
                        "safety_checks": ",".join(p2_safety),
                    }
                )

            # adopt latest patrol time (max)
            times = []
            for p in patrol_list:
                t = _try_time("未選択" if p["patrol_time_hh"] is None else p["patrol_time_hh"],
                              "未選択" if p["patrol_time_mm"] is None else p["patrol_time_mm"])
                if t:
                    times.append(t)
            patrol_main_time = max(times) if times else None

        st.markdown("</div>", unsafe_allow_html=True)

        

# ---------------- ① 支援記録 ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        title_1_cls = "section-title danger" if is_special_typing else "section-title"
        st.markdown(f'<div class="{title_1_cls}">① 支援記録</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">時刻は「巡視があれば最新巡視時刻」、なければ「現在時刻」を自動採用します。</div>', unsafe_allow_html=True)

        add_scene = st.selectbox("場面", SCENES, index=2, format_func=scene_display, key=add_key("add_scene"))

        scene_note = ""
        if str(add_scene) != "":
            scene_note = st.text_input(
                "記録内容（フリーワード）",
                value="",
                key=add_key("scene_note"),
                placeholder="例：表情良好／声かけで落ち着く／水分摂取 等",
            )

        # Optional manual time override
        now_dt = datetime.now()
        default_time = now_dt.replace(minute=(now_dt.minute // 5) * 5, second=0, microsecond=0).time()
        change_time = st.toggle("時刻を手動で変更する（通常は不要）", value=False, key=add_key("manual_time_toggle"))
        manual_time = None
        if change_time:
            manual_time = st.time_input("時刻", value=default_time, key=add_key("manual_time_value"))
        st.markdown("</div>", unsafe_allow_html=True)

        

# Decide main record time
        if enable_patrol and patrol_main_time is not None:
            auto_hh, auto_mm = patrol_main_time
        else:
            auto_hh, auto_mm = default_time.hour, default_time.minute

        if change_time and manual_time is not None:
            record_hh, record_mm = manual_time.hour, manual_time.minute
        else:
            record_hh, record_mm = int(auto_hh), int(auto_mm)

        st.caption(f"🕒 主時刻：{record_hh:02d}:{record_mm:02d}（自動採用）")

        # ---------------- ② バイタル ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">② バイタル（朝・夕）</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">前回値を自動セット（なければ標準値）。数字を少し変えるだけで入力できます。</div>', unsafe_allow_html=True)

        st.markdown("**朝**")
        am_unmeasured = st.toggle("朝：未測定（未入力で保存）", value=False, key=add_key("am_unmeasured"))
        am_temp = st.number_input("朝 体温（℃）", value=float(dv("temp_am", "float")), step=0.1, format="%.1f",
                                  disabled=am_unmeasured, key=add_key("am_temp"))
        am_sys = st.number_input("朝 血圧 上", value=int(dv("bp_sys_am", "int")), step=1,
                                 disabled=am_unmeasured, key=add_key("am_sys"))
        am_dia = st.number_input("朝 血圧 下", value=int(dv("bp_dia_am", "int")), step=1,
                                 disabled=am_unmeasured, key=add_key("am_dia"))
        am_pulse = st.number_input("朝 脈拍", value=int(dv("pulse_am", "int")), step=1,
                                   disabled=am_unmeasured, key=add_key("am_pulse"))
        am_spo2 = st.number_input("朝 SpO₂", value=int(dv("spo2_am", "int")), step=1,
                                  disabled=am_unmeasured, key=add_key("am_spo2"))

        st.divider()
        st.markdown("**夕**")
        pm_unmeasured = st.toggle("夕：未測定（未入力で保存）", value=False, key=add_key("pm_unmeasured"))
        pm_temp = st.number_input("夕 体温（℃）", value=float(dv("temp_pm", "float")), step=0.1, format="%.1f",
                                  disabled=pm_unmeasured, key=add_key("pm_temp"))
        pm_sys = st.number_input("夕 血圧 上", value=int(dv("bp_sys_pm", "int")), step=1,
                                 disabled=pm_unmeasured, key=add_key("pm_sys"))
        pm_dia = st.number_input("夕 血圧 下", value=int(dv("bp_dia_pm", "int")), step=1,
                                 disabled=pm_unmeasured, key=add_key("pm_dia"))
        pm_pulse = st.number_input("夕 脈拍", value=int(dv("pulse_pm", "int")), step=1,
                                   disabled=pm_unmeasured, key=add_key("pm_pulse"))
        pm_spo2 = st.number_input("夕 SpO₂", value=int(dv("spo2_pm", "int")), step=1,
                                  disabled=pm_unmeasured, key=add_key("pm_spo2"))
        st.markdown("</div>", unsafe_allow_html=True)

        # ---------------- ③ 食事 ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">③ 食事</div>', unsafe_allow_html=True)

        bf_done = st.toggle("朝食あり", value=False, key=add_key("add_bf_done"))
        bf_score = st.slider("朝食量（1〜10）", 1, 10, value=5, key=add_key("f_bf_score"), disabled=(not bf_done))
        lu_done = st.toggle("昼食あり", value=False, key=add_key("add_lu_done"))
        lu_score = st.slider("昼食量（1〜10）", 1, 10, value=5, key=add_key("f_lu_score"), disabled=(not lu_done))
        di_done = st.toggle("夕食あり", value=False, key=add_key("add_di_done"))
        di_score = st.slider("夕食量（1〜10）", 1, 10, value=5, key=add_key("f_di_score"), disabled=(not di_done))
        st.markdown("</div>", unsafe_allow_html=True)

        # ---------------- ④ 服薬 ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">④ 服薬</div>', unsafe_allow_html=True)
        med_m = st.checkbox("朝", value=False, key=add_key("add_med_m"))
        med_n = st.checkbox("昼", value=False, key=add_key("add_med_n"))
        med_e = st.checkbox("夕", value=False, key=add_key("add_med_e"))
        med_b = st.checkbox("寝る前", value=False, key=add_key("add_med_b"))
        st.markdown("</div>", unsafe_allow_html=True)

        # ---------------- ⑥ 特記事項 ----------------
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⑥ 特記事項</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">1文字でも入力があると、タイトル/保存ボタンが赤になります。保存すると「申し送り」にも反映。</div>', unsafe_allow_html=True)

        special_flag = st.checkbox("⚠ 特記事項あり（申し送りにも共有する）", value=False, key=add_key("special_flag"))
        note = st.text_area(
            "特記事項（自由記述）",
            value="",
            height=200,
            key=add_key("add_note"),
            placeholder="例：普段と違う行動／不穏／転倒・ヒヤリ／対応内容と結果／家族・医療連携 等",
        )

        st.markdown(f"<div class='{ 'danger-save' if (special_flag or (note or '').strip()) else 'bottom-save' }'>", unsafe_allow_html=True)
        save_clicked_bottom = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("bottom_save_btn"))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # ---------------- Save logic ----------------
        save_clicked = bool(save_clicked_top or save_clicked_bottom)
        if save_clicked:
            if recorder_name.strip() == "":
                st.error("サイドバーで「記録者名（必須）」を入力してください。")
            else:
                # NULL if unmeasured
                am_temp_v = None if am_unmeasured else float(am_temp)
                am_sys_v = None if am_unmeasured else int(am_sys)
                am_dia_v = None if am_unmeasured else int(am_dia)
                am_pulse_v = None if am_unmeasured else int(am_pulse)
                am_spo2_v = None if am_unmeasured else int(am_spo2)

                pm_temp_v = None if pm_unmeasured else float(pm_temp)
                pm_sys_v = None if pm_unmeasured else int(pm_sys)
                pm_dia_v = None if pm_unmeasured else int(pm_dia)
                pm_pulse_v = None if pm_unmeasured else int(pm_pulse)
                pm_spo2_v = None if pm_unmeasured else int(pm_spo2)

                wakeup_flag = 1 if str(add_scene) == "起床" else 0

                combined_note = (note or "").strip()

                payload = {
                    "id": None,
                    "unit_id": unit_id,
                    "resident_id": selected,
                    "record_date": target_date_str,
                    "record_time_hh": int(record_hh),
                    "record_time_mm": int(record_mm),
                    "shift": shift,
                    "recorder_name": recorder_name.strip(),
                    "scene": add_scene if add_scene in SCENES else "ご様子",
                    "scene_note": (scene_note or "").strip() if str(add_scene) != "" else "",
                    "wakeup_flag": wakeup_flag,

                    "temp_am": am_temp_v,
                    "bp_sys_am": am_sys_v,
                    "bp_dia_am": am_dia_v,
                    "pulse_am": am_pulse_v,
                    "spo2_am": am_spo2_v,

                    "temp_pm": pm_temp_v,
                    "bp_sys_pm": pm_sys_v,
                    "bp_dia_pm": pm_dia_v,
                    "pulse_pm": pm_pulse_v,
                    "spo2_pm": pm_spo2_v,

                    "meal_bf_done": 1 if bf_done else 0,
                    "meal_bf_score": int(bf_score) if bf_done else 0,
                    "meal_lu_done": 1 if lu_done else 0,
                    "meal_lu_score": int(lu_score) if lu_done else 0,
                    "meal_di_done": 1 if di_done else 0,
                    "meal_di_score": int(di_score) if di_done else 0,

                    "med_morning": 1 if med_m else 0,
                    "med_noon": 1 if med_n else 0,
                    "med_evening": 1 if med_e else 0,
                    "med_bed": 1 if med_b else 0,

                    "note": combined_note,
                }

                record_id = upsert_record(conn, payload, patrol_list)

                # ⑥ -> handover (when checkbox ON or note exists? requirement says when special exists; keep checkbox OR note)
                if (bool(special_flag) or (combined_note != "")) and combined_note:
                    add_handover_from_note(
                        conn,
                        unit_id=unit_id,
                        resident_id=selected,
                        handover_date=target_date_str,
                        content=combined_note,
                        created_by=recorder_name.strip(),
                        source_record_id=record_id,
                    )

                bump_epoch_and_rerun()

    # ======================================================================
    # 経過一覧 TAB
    # ======================================================================
    with tab_list:
        selected = int(st.session_state.get("selected_resident_id"))
        sel_row = residents_df.loc[residents_df["id"] == selected].iloc[0]
        sel_name = str(sel_row["name"])
        st.markdown(f'<div class="app-title">📋 経過一覧 <span class="muted">{sel_name}（{target_date_str}）</span></div>', unsafe_allow_html=True)

        recs = list_records_for_day(conn, selected, target_date_str)
        if recs.empty:
            st.info("この日の記録はまだありません。")
        else:
            for _, r in recs.iterrows():
                rid = int(r["id"])
                t = fmt_time(r.get("record_time_hh"), r.get("record_time_mm"))
                scene = scene_display(r.get("scene"))
                scene_note2 = (r.get("scene_note") or "").strip()

                note_head = str(r.get("note_head") or "")
                has_note = len(note_head.strip()) > 0

                st.markdown('<div class="record-card">', unsafe_allow_html=True)
                st.markdown(f"**{t}**　{scene}　/ 記録者：{r['recorder_name']}")
                if scene_note2:
                    st.markdown(f"- 場面メモ：{scene_note2}")

                # vitals (no 0 display)
                vitals_html = build_vital_section(r)
                if vitals_html:
                    st.markdown(vitals_html, unsafe_allow_html=True)

                # special note: vivid red + bold
                if has_note:
                    st.markdown(f"<div style='color:var(--danger);font-weight:1000;'>⚠ 特記事項：{note_head}</div>", unsafe_allow_html=True)
                else:
                    st.caption("特記事項なし")

                # patrol inline (if exists)
                patrol_count = int(r.get("patrol_count", 0) or 0)
                if patrol_count > 0:
                    st.markdown(build_patrol_inline(conn, rid), unsafe_allow_html=True)

                if st.button("🗑️ この記録を削除（論理削除）", key=f"del_btn_{rid}", use_container_width=True):
                    soft_delete_record(conn, rid)
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    # ======================================================================
    # 申し送り TAB
    # ======================================================================
    with tab_ho:
        st.markdown(f'<div class="app-title">🗒️ 申し送り <span class="muted">{unit_name} / {target_date_str}</span></div>', unsafe_allow_html=True)
        st.caption("👍 いいねで「誰が確認したか」を可視化します（確認ボタンはありません）。")

        ho = list_handovers(conn, unit_id=unit_id, handover_date=target_date_str)
        if ho.empty:
            st.info("この日の申し送りはまだありません。")
        else:
            res_map = {int(r["id"]): str(r["name"]) for _, r in residents_df.iterrows()}
            for _, h in ho.iterrows():
                hid = int(h["id"])
                rid = safe_int(h.get("resident_id"))
                rname = res_map.get(int(rid), "（全体）") if rid is not None else "（全体）"

                who = str(h.get("created_by") or "")
                content = str(h.get("content") or "").strip()
                created_at = fmt_dt(h.get("created_at"))

                reacts = list_reactions(conn, hid)
                likes = reacts.loc[reacts["reaction_type"] == "like"].copy() if not reacts.empty else pd.DataFrame(columns=["user_name","reaction_type","created_at"])
                like_names = [str(x) for x in likes["user_name"].tolist()] if not likes.empty else []
                like_count = len(like_names)

                # compact label: 👍 3（A、B、C）
                names_preview = "、".join(like_names[:8])
                if like_count > 8:
                    names_preview += "…"
                label = f"👍 {like_count}"
                if like_count > 0:
                    label += f"（{names_preview}）"

                liked_by_me = False
                if recorder_name.strip():
                    liked_by_me = has_reaction(conn, handover_id=hid, user_name=recorder_name.strip(), reaction_type="like")

                st.markdown('<div class="handover-card">', unsafe_allow_html=True)
                # NOTE: keep this as a single-line f-string to avoid unterminated literals
                st.markdown(f"**{rname}**  \n{content}")
                st.markdown(f"<div class='handover-meta'>投稿：{created_at}｜投稿者：{who}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='handover-meta' style='font-weight:1000;'>{label}</div>", unsafe_allow_html=True)

                btn_txt = "👍 いいね" if not liked_by_me else "👍 いいね済み（取り消し）"
                if st.button(btn_txt, key=f"ho_like_{hid}", use_container_width=True):
                    if recorder_name.strip():
                        toggle_reaction(conn, handover_id=hid, user_name=recorder_name.strip(), reaction_type="like")
                        st.rerun()
                    else:
                        st.warning("サイドバーで『記録者名』を入力すると、誰がいいねしたか記録できます。")

                # optional: show timestamps
                if like_count > 0:
                    with st.expander("👍 いいね履歴（誰がいつ）", expanded=False):
                        likes2 = likes.sort_values("created_at", ascending=True)
                        for _, lr in likes2.iterrows():
                            uname = str(lr.get("user_name") or "")
                            ts = fmt_dt(lr.get("created_at"))
                            st.markdown(f"- {uname}（{ts}）")

                st.markdown("</div>", unsafe_allow_html=True)

    conn.close()


if __name__ == "__main__":
    main()
