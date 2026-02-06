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
  --danger:#b91c1c;
  --warn:#b45309;
  --ok:#047857;
  --shadow: 0 10px 30px rgba(15,23,42,0.08);
  --shadow2: 0 2px 12px rgba(15,23,42,0.06);
  --highlight-bg: rgba(253, 230, 138, 0.35);
  --highlight-border: rgba(245, 158, 11, 0.85);
}

.stApp { background: var(--bg); color: var(--text); }
.block-container { padding-top: 1.0rem; padding-bottom: 2.8rem; }

/* title: smaller + clean */
.app-title{
  font-size: 26px;
  font-weight: 1000;
  letter-spacing: .2px;
  margin: 0 0 4px 0;
}

    .resident-meta{font-size:12px;color:rgba(15,23,42,0.68);margin-top:-8px;margin-bottom:10px;}
.app-title .muted{ color: rgba(15,23,42,0.72); font-weight: 900; }
@media (max-width: 860px){
  .app-title{ font-size: 22px; }
}

/* record cards */
.record-card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px 18px 16px 18px;
  box-shadow: var(--shadow2);
  margin: 10px 0 14px 0;
}
.record-card:hover{
  box-shadow: var(--shadow);
  transition: 160ms ease;
}

.section-title{
  font-size: 16px;
  font-weight: 900;
  margin: 0 0 10px 0;
  padding-left: 12px;
  border-left: 6px solid var(--accent);
  line-height: 1.2;
}
.section-title.danger{
  border-left-color: var(--danger);
  color: var(--danger);
}
.section-sub{
  color: var(--muted);
  font-size: 12px;
  margin-top: -6px;
  margin-bottom: 10px;
}

/* top / bottom save */
.top-save .stButton > button,
.bottom-save .stButton > button{
  width:100% !important;
  border-radius: 14px !important;
  padding: 0.84rem 1.0rem !important;
  font-weight: 1000 !important;
  background: var(--accent2) !important;
  border: 1px solid rgba(0,0,0,0.05) !important;
  color: white !important;
  box-shadow: 0 14px 30px rgba(37,99,235,0.18);
}
.top-save .stButton > button:hover,
.bottom-save .stButton > button:hover{
  filter: brightness(0.98);
  transform: translateY(-1px);
  transition: 140ms ease;
}

/* handover cards */
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
.handover-actions{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  margin-top: 10px;
}
.reaction-chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(15,23,42,0.03);
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

textarea{ border-radius: 14px !important; }

section[data-testid="stSidebar"]{
  border-right: 1px solid var(--border);
  background: #ffffff;
}
[data-testid="stCaptionContainer"]{ color: var(--muted); }

/* Recorder highlight */
.recorder-highlight{
  background: var(--highlight-bg);
  border: 3px solid var(--highlight-border);
  border-radius: 14px;
  padding: 10px 10px 6px 10px;
  margin-top: 6px;
}
.recorder-highlight .label{
  font-weight: 1000;
  color: rgba(15,23,42,0.90);
  font-size: 13px;
  margin-bottom: 6px;
}
.recorder-warn{
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(185,28,28,0.25);
  background: rgba(185,28,28,0.08);
  color: rgba(185,28,28,0.95);
  font-size: 12px;
  font-weight: 900;
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
    st.set_page_config(page_title="介護記録（監査対応版）", layout="wide")
    inject_css()
    ensure_epoch()

    conn = get_conn()
    init_db(conn)

    # Sidebar
    st.sidebar.title("📌 条件")
    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット", units_df["name"].tolist(), index=0)
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    target_date = st.sidebar.date_input("日付", value=date.today())
    target_date_str = target_date.isoformat()

    st.sidebar.divider()
    shift = st.sidebar.radio("勤務区分", ["日勤", "夜勤"], index=0)

    # Recorder highlight
    st.sidebar.markdown("<div class='recorder-highlight'><div class='label'>✍️ 記録者名（必須 / 申し送りの表示名にも使います）</div>", unsafe_allow_html=True)
    recorder_name = st.sidebar.text_input("記録者名", value=st.session_state.get("recorder_name", ""), key="recorder_name_sidebar")
    st.session_state["recorder_name"] = recorder_name
    if recorder_name.strip() == "":
        st.sidebar.markdown("<div class='recorder-warn'>⚠ 記録者名が未入力です（保存できません / リアクションも不可）</div>", unsafe_allow_html=True)
    st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.divider()
    if st.sidebar.button("🤖 AI支援案（準備枠）", use_container_width=True):
        msg = generate_ai_care_suggestions(conn, unit_id, target_date_str)
        st.sidebar.success(msg)

    # Title (smaller)
    st.markdown('<div class="app-title">🧾 介護記録 <span class="muted">（監査対応 / 清潔プロUI）</span></div>', unsafe_allow_html=True)
    st.caption("保存後は epoch 方式で安全に初期化し、st.rerun() で一覧を即更新します。")
    show_toast_if_needed()

    residents_df = fetch_df(
        conn,
        "SELECT id, name, kubun, disease FROM residents WHERE unit_id=? AND is_active=1 ORDER BY name;",
        (unit_id,),
    )

    if "selected_resident_id" not in st.session_state:
        st.session_state["selected_resident_id"] = None

    # -------------------------
    # 利用者カード一覧
    # -------------------------
    st.subheader("👥 利用者")
    cols = st.columns(3)
    for idx, row in residents_df.iterrows():
        rid = int(row["id"])
        nm = str(row["name"])
        kubun = str(row.get("kubun") or "")
        disease = str(row.get("disease") or "")
        info_line = ""
        if kubun.strip() or disease.strip():
            k = kubun.strip() if kubun.strip() else "-"
            d = disease.strip() if disease.strip() else "-"
            info_line = f"区分：{k} / 病名：{d}"
        else:
            info_line = "区分：- / 病名：-"
        latest = get_latest_for_resident(conn, rid, target_date_str)

        if latest is None:
            patrol_count = 0
            temp_line = "体温: -"
            meal_line = "食事: -"
            badge = "未入力"
        else:
            temp_am = latest["temp_am"]
            temp_pm = latest["temp_pm"]
            bf_done0 = int(latest["meal_bf_done"])
            bf_score0 = int(latest["meal_bf_score"])
            lu_done0 = int(latest["meal_lu_done"])
            lu_score0 = int(latest["meal_lu_score"])
            di_done0 = int(latest["meal_di_done"])
            di_score0 = int(latest["meal_di_score"])
            patrol_count = int(latest.get("patrol_count", 0) or 0)
            badge = "更新あり"

            t1 = "-" if temp_am is None else f"{float(temp_am):.1f}"
            t2 = "-" if temp_pm is None else f"{float(temp_pm):.1f}"
            temp_line = f"体温: 朝{t1}/夕{t2}"
            meal_line = f"食事: 朝{(bf_score0 if bf_done0 else '-')}/昼{(lu_score0 if lu_done0 else '-')}/夕{(di_score0 if di_done0 else '-')}"
        c = cols[idx % 3]
        with c:
            st.markdown(
                f"""
<div class="record-card">
  <div class="section-title">{nm}</div>
  <div class="section-sub"><span style='font-size:12px;color:rgba(15,23,42,0.68);'>{info_line}</span><br>{badge} / {temp_line} / {meal_line} / 巡視:{patrol_count}回</div>
</div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("開く", key=f"open_{rid}", use_container_width=True):
                st.session_state["selected_resident_id"] = rid
                st.session_state["edit_record_id"] = None
                st.rerun()

    st.divider()

    selected = st.session_state.get("selected_resident_id")
    if selected is None:
        st.info("上の一覧から利用者を選択してください。")
        conn.close()
        return

    sel_row = residents_df.loc[residents_df["id"] == selected].iloc[0]
    sel_name = str(sel_row["name"])
    sel_kubun = str(sel_row.get("kubun") or "-")
    sel_disease = str(sel_row.get("disease") or "-")
    sel_info = f"区分：{sel_kubun if str(sel_kubun).strip() else '-'} / 病名：{sel_disease if str(sel_disease).strip() else '-'}"

    # Tabs
    tab_record, tab_handover = st.tabs(["✍️ 記録入力・一覧", "🗒️ 申し送り（連絡帳）"])

    # -------------------------
    # Record tab
    # -------------------------
    with tab_record:
        # ✅ タイトル行 + 保存ボタン（右横・横並び）
        title_col, btn_col = st.columns([7.2, 2.8])
        with title_col:
            st.subheader(f"✍️ 入力 / 一覧：{sel_name} 様（{target_date_str}）")
            st.markdown(f"<div class='resident-meta'>{sel_info}</div>", unsafe_allow_html=True)
        with btn_col:
            st.markdown("<div class='top-save'>", unsafe_allow_html=True)
            save_clicked_top = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("top_save_btn"))
            st.markdown("</div>", unsafe_allow_html=True)

        # ---- options
        hh_options = ["未選択"] + list(range(0, 24))
        mm_options = ["未選択"] + list(range(0, 60, 5))
        safety_options = ["室温OK", "体調変化なし", "危険物なし", "転倒リスクなし"]
        patrol_status_options = ["", "就寝中（静か）", "起きている（静か）", "起きている（落ち着かない）", "不穏", "不在"]

        # Prefill vitals (latest or standard)
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

        # ① 支援記録（時刻・場面）
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)

            # ⑥特記事項が入力中なら、①タイトルをdangerで強調（動的）
            # ※ noteは後で作るので、session_stateの該当キーがまだ無い場合は空扱いにする
            note_preview = (st.session_state.get(add_key("add_note"), "") or "").strip()
            special_flag_preview = bool(st.session_state.get(add_key("special_flag"), False))
            special_tags_preview = st.session_state.get(add_key("special_tags"), []) or []
            is_special_typing = special_flag_preview or (len(special_tags_preview) > 0) or (len(note_preview) > 0)

            title_cls = "section-title danger" if is_special_typing else "section-title"
            st.markdown(f'<div class="{title_cls}">① 支援記録（時刻・場面）</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-sub">時刻は必須。場面が未選択以外の場合のみ、フリーワードが表示されます。</div>', unsafe_allow_html=True)

            if is_special_typing:
                st.markdown(
                    "<div style='margin-top:-2px;margin-bottom:10px;color:var(--danger);font-weight:900;font-size:12px;'>"
                    "⚠ ⑥ 特記事項が入力中です（いつもと違う行動・特記）→ 記録の整合に注意</div>",
                    unsafe_allow_html=True,
                )

            # ---- 巡視入力時は「巡視時刻」を主時刻として自動採用（時刻二度手間を解消）
            patrol_mode_preview = bool(st.session_state.get(add_key("add_enable_patrol"), False))
            p1_hh_prev = st.session_state.get(add_key("p1_hh"), "未選択")
            p1_mm_prev = st.session_state.get(add_key("p1_mm"), "未選択")
            p2_hh_prev = st.session_state.get(add_key("p2_hh"), "未選択")
            p2_mm_prev = st.session_state.get(add_key("p2_mm"), "未選択")

            def _patrol_time(hh, mm):
                if hh == "未選択" or mm == "未選択":
                    return None
                try:
                    return (int(hh), int(mm))
                except Exception:
                    return None

            patrol_times = [t for t in [_patrol_time(p1_hh_prev, p1_mm_prev), _patrol_time(p2_hh_prev, p2_mm_prev)] if t]
            patrol_main_time = min(patrol_times) if patrol_times else None

            c1, c2, c3 = st.columns([1, 1, 1.4])
            if patrol_mode_preview:
                # 巡視を記録する場合は、巡視の時刻を主時刻として採用（時刻入力欄は非表示）
                add_hh, add_mm = patrol_main_time if patrol_main_time is not None else ("未選択", "未選択")
                with c1:
                    st.markdown("**時**")
                    if isinstance(add_hh, str):
                        st.markdown("<span style='font-size:14px;color:var(--muted);'>未選択</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='font-size:18px;font-weight:1000;color:var(--accent2);'>{int(add_hh):02d}</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**分**")
                    if isinstance(add_mm, str):
                        st.markdown("<span style='font-size:14px;color:var(--muted);'>未選択</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='font-size:18px;font-weight:1000;color:var(--accent2);'>{int(add_mm):02d}</span>", unsafe_allow_html=True)
                with c3:
                    add_scene = st.selectbox("場面", SCENES, index=2, format_func=scene_display, key=add_key("add_scene"))
                st.caption("※ 巡視を記録する場合、巡視の『時・分』を主時刻として自動採用します（時刻の二度手間をなくします）。")
            else:
                with c1:
                    add_hh = st.selectbox("時", hh_options, index=0, key=add_key("add_time_hh"))
                with c2:
                    add_mm = st.selectbox("分（5分刻み）", mm_options, index=0, key=add_key("add_time_mm"))
                with c3:
                    add_scene = st.selectbox("場面", SCENES, index=2, format_func=scene_display, key=add_key("add_scene"))

            if str(add_scene) != "":
                scene_note = st.text_input(
                    "記録内容（フリーワード）",
                    value="",
                    key=add_key("scene_note"),
                    placeholder="例：起床後に水分摂取／表情良好／声かけで落ち着く 等",
                )
            else:
                scene_note = ""
                st.caption("※ 場面を選択すると、フリーワード入力欄が表示されます。")

            st.markdown("</div>", unsafe_allow_html=True)

        # ② バイタル
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">② バイタル（朝・夕）</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-sub">直近の値を引き継ぎ（なければ標準値）。「未測定」をONにすると未入力（NULL保存）にできます。</div>', unsafe_allow_html=True)

            st.markdown("**朝**")
            am_unmeasured = st.toggle("朝：未測定（未入力で保存）", value=False, key=add_key("am_unmeasured"))
            v1, v2, v3, v4, v5 = st.columns(5)
            with v1:
                am_temp = st.number_input("体温（℃）", value=float(dv("temp_am", "float")), step=0.1, format="%.1f",
                                          disabled=am_unmeasured, key=add_key("am_temp"))
            with v2:
                am_sys = st.number_input("血圧 上", value=int(dv("bp_sys_am", "int")), step=1,
                                         disabled=am_unmeasured, key=add_key("am_sys"))
            with v3:
                am_dia = st.number_input("血圧 下", value=int(dv("bp_dia_am", "int")), step=1,
                                         disabled=am_unmeasured, key=add_key("am_dia"))
            with v4:
                am_pulse = st.number_input("脈拍", value=int(dv("pulse_am", "int")), step=1,
                                           disabled=am_unmeasured, key=add_key("am_pulse"))
            with v5:
                am_spo2 = st.number_input("SpO₂", value=int(dv("spo2_am", "int")), step=1,
                                          disabled=am_unmeasured, key=add_key("am_spo2"))

            st.markdown("**夕**")
            pm_unmeasured = st.toggle("夕：未測定（未入力で保存）", value=False, key=add_key("pm_unmeasured"))
            w1, w2, w3, w4, w5 = st.columns(5)
            with w1:
                pm_temp = st.number_input("体温（℃） ", value=float(dv("temp_pm", "float")), step=0.1, format="%.1f",
                                          disabled=pm_unmeasured, key=add_key("pm_temp"))
            with w2:
                pm_sys = st.number_input("血圧 上 ", value=int(dv("bp_sys_pm", "int")), step=1,
                                         disabled=pm_unmeasured, key=add_key("pm_sys"))
            with w3:
                pm_dia = st.number_input("血圧 下 ", value=int(dv("bp_dia_pm", "int")), step=1,
                                         disabled=pm_unmeasured, key=add_key("pm_dia"))
            with w4:
                pm_pulse = st.number_input("脈拍 ", value=int(dv("pulse_pm", "int")), step=1,
                                           disabled=pm_unmeasured, key=add_key("pm_pulse"))
            with w5:
                pm_spo2 = st.number_input("SpO₂ ", value=int(dv("spo2_pm", "int")), step=1,
                                          disabled=pm_unmeasured, key=add_key("pm_spo2"))

            st.markdown("</div>", unsafe_allow_html=True)

        # ③ 食事
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">③ 食事</div>', unsafe_allow_html=True)

            m1, m2, m3 = st.columns(3)
            with m1:
                bf_done = st.toggle("朝食あり", value=False, key=add_key("add_bf_done"))
                bf_score = st.slider("朝食量（1〜10）", 1, 10, value=5, key=add_key("f_bf_score"), disabled=(not bf_done))
            with m2:
                lu_done = st.toggle("昼食あり", value=False, key=add_key("add_lu_done"))
                lu_score = st.slider("昼食量（1〜10）", 1, 10, value=5, key=add_key("f_lu_score"), disabled=(not lu_done))
            with m3:
                di_done = st.toggle("夕食あり", value=False, key=add_key("add_di_done"))
                di_score = st.slider("夕食量（1〜10）", 1, 10, value=5, key=add_key("f_di_score"), disabled=(not di_done))

            st.markdown("</div>", unsafe_allow_html=True)

        # ④ 服薬
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">④ 服薬</div>', unsafe_allow_html=True)

            a, b, c, d = st.columns(4)
            with a:
                med_m = st.checkbox("朝", value=False, key=add_key("add_med_m"))
            with b:
                med_n = st.checkbox("昼", value=False, key=add_key("add_med_n"))
            with c:
                med_e = st.checkbox("夕", value=False, key=add_key("add_med_e"))
            with d:
                med_b = st.checkbox("寝る前", value=False, key=add_key("add_med_b"))

            st.markdown("</div>", unsafe_allow_html=True)

        # ⑤ 巡視
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">⑤ 巡視</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-sub">ONで巡視1/2の入力欄が表示されます。</div>', unsafe_allow_html=True)

            enable_patrol = st.checkbox("巡視を記録する", value=False, key=add_key("add_enable_patrol"))

            patrol_list = []
            if enable_patrol:
                pcol1, pcol2 = st.columns(2)
                with pcol1:
                    st.markdown("**巡視1**")
                    p1_hh = st.selectbox("時", hh_options, index=0, key=add_key("p1_hh"))
                    p1_mm = st.selectbox("分", mm_options, index=0, key=add_key("p1_mm"))
                    p1_status = st.selectbox("状況", patrol_status_options, index=0, key=add_key("p1_status"))
                    p1_memo = st.text_input("メモ", value="", key=add_key("p1_memo"))
                    p1_int = st.checkbox("対応した", value=False, key=add_key("p1_int"))
                    p1_door = st.checkbox("居室ドアを開けた", value=False, key=add_key("p1_door"))
                    p1_safety = st.multiselect("安全チェック", safety_options, default=[], key=add_key("p1_safety"))

                with pcol2:
                    st.markdown("**巡視2**")
                    p2_hh = st.selectbox("時 ", hh_options, index=0, key=add_key("p2_hh"))
                    p2_mm = st.selectbox("分 ", mm_options, index=0, key=add_key("p2_mm"))
                    p2_status = st.selectbox("状況 ", patrol_status_options, index=0, key=add_key("p2_status"))
                    p2_memo = st.text_input("メモ ", value="", key=add_key("p2_memo"))
                    p2_int = st.checkbox("対応した ", value=False, key=add_key("p2_int"))
                    p2_door = st.checkbox("居室ドアを開けた ", value=False, key=add_key("p2_door"))
                    p2_safety = st.multiselect("安全チェック ", safety_options, default=[], key=add_key("p2_safety"))

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

            st.markdown("</div>", unsafe_allow_html=True)

        # ⑥ 特記事項（普段と行動が違う等）
        with st.container():
            st.markdown('<div class="record-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">⑥ 特記事項（普段と行動が違う等）</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-sub">いつもと違う様子や、特記すべき事項を詳細に記入してください。保存すると自動で「申し送り」にも反映されます。</div>', unsafe_allow_html=True)

            special_flag = st.checkbox("⚠ 特記事項あり（申し送りにも共有する）", value=False, key=add_key("special_flag"))
            special_tags = st.multiselect(
                "該当（任意）",
                ["不穏", "発熱", "転倒・ヒヤリハット", "食事低下", "服薬関連", "対人", "金銭", "外出/外泊", "医療連携", "家族連絡", "その他"],
                default=[],
                key=add_key("special_tags"),
            )

            note = st.text_area(
                "特記事項（自由記述）",
                value="",
                height=220,
                key=add_key("add_note"),
                placeholder="例：普段と違う行動／不穏の兆候／転倒・ヒヤリハット／対応内容と結果／家族・医療連携 等",
            )

            # ✅ 追加の大きい保存ボタン（⑥の直下）
            st.markdown("<div class='bottom-save'>", unsafe_allow_html=True)
            save_clicked_bottom = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("bottom_save_btn"))
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

        # -------------------------
        # ✅ 保存処理（top/bottomどちらでも）
        # -------------------------
        save_clicked = bool(save_clicked_top or save_clicked_bottom)
        if save_clicked:
            if recorder_name.strip() == "":
                st.error("記録者名（必須）を入力してください。サイドバーの黄色枠が対象です。")
            else:
                def _is_unselected(v):
                    return v is None or (isinstance(v, str) and v == "未選択")

                # 巡視入力時は巡視時刻が主時刻になるため、時刻入力の二度手間をなくす
                can_save = True
                if patrol_mode_preview:
                    if patrol_main_time is None:
                        st.error("巡視を記録する場合は、巡視1/2の『時・分』を選択してください（主時刻として自動採用します）。")
                        can_save = False
                else:
                    if _is_unselected(add_hh) or _is_unselected(add_mm):
                        st.error("時刻（時・分）を選択してください。未選択のままだと誤連投が起きます。")
                        can_save = False

                if can_save:
                    def n_real(x):
                        # 未測定なら None
                        return None if x is None else float(x)
    
                    def n_int(x):
                        return None if x is None else int(x)
    
                    wakeup_flag = 1 if str(add_scene) == "起床" else 0
    
                    # 未測定ONなら全部None
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
    
                    # ---- ⑥ 特記事項（タグ付け） ----
                    tag_prefix = ""
                    if (special_tags or []):
                        tag_prefix = "【特記事項タグ：" + "、".join([str(t) for t in special_tags]) + "】\n"
                    combined_note = (note or "").strip()
                    if tag_prefix:
                        combined_note = (tag_prefix + combined_note) if combined_note else tag_prefix.strip()
    
                    payload = {
                        "id": None,
                        "unit_id": unit_id,
                        "resident_id": selected,
                        "record_date": target_date_str,
                        "record_time_hh": int(add_hh),
                        "record_time_mm": int(add_mm),
                        "shift": shift,
                        "recorder_name": recorder_name.strip(),
                        "scene": add_scene if add_scene in SCENES else "ご様子",
                        "scene_note": (scene_note or "").strip() if str(add_scene) != "" else "",
                        "wakeup_flag": wakeup_flag,
    
                        "temp_am": n_real(am_temp_v),
                        "bp_sys_am": n_int(am_sys_v),
                        "bp_dia_am": n_int(am_dia_v),
                        "pulse_am": n_int(am_pulse_v),
                        "spo2_am": n_int(am_spo2_v),
    
                        "temp_pm": n_real(pm_temp_v),
                        "bp_sys_pm": n_int(pm_sys_v),
                        "bp_dia_pm": n_int(pm_dia_v),
                        "pulse_pm": n_int(pm_pulse_v),
                        "spo2_pm": n_int(pm_spo2_v),
    
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
    
                    # ✅ ⑥ 特記事項 → 申し送りへ自動連携（チェック時のみ）
                    if bool(special_flag) and (combined_note or "").strip():
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

        st.divider()

        # -------------------------
        # List / Delete（監査表示）
        # -------------------------
        st.markdown("### 📋 支援記録一覧（完全時系列 / 監査向け表示）")
        recs = list_records_for_day(conn, selected, target_date_str)

        if recs.empty:
            st.info("この日の記録はまだありません。")
        else:
            for _, r in recs.iterrows():
                rid = int(r["id"])
                t = fmt_time(r.get("record_time_hh"), r.get("record_time_mm"))
                scene = scene_display(r.get("scene"))

                patrol_count = int(r.get("patrol_count", 0) or 0)
                patrol_badge = ""
                if patrol_count > 0:
                    patrol_badge = f"<span class='reaction-chip'>✅ 巡視 {patrol_count}回</span>"

                created_at = fmt_dt(r.get("created_at"))
                updated_at = fmt_dt(r.get("updated_at"))
                meta_html = f"作成:{created_at}<br>更新:{updated_at}"

                # badges
                badges = []
                meds_any = (int(r["med_morning"]) == 1 or int(r["med_noon"]) == 1 or int(r["med_evening"]) == 1 or int(r["med_bed"]) == 1)
                if meds_any:
                    badges.append("<span class='reaction-chip'>💊 服薬</span>")

                t_am = safe_float(r.get("temp_am"))
                t_pm = safe_float(r.get("temp_pm"))
                if t_am is not None and float(t_am) >= 37.5:
                    badges.append("<span class='reaction-chip' style='border-color:rgba(185,28,28,0.25);background:rgba(185,28,28,0.08);'>🌡️ 朝 発熱</span>")
                if t_pm is not None and float(t_pm) >= 37.5:
                    badges.append("<span class='reaction-chip' style='border-color:rgba(185,28,28,0.25);background:rgba(185,28,28,0.08);'>🌡️ 夕 発熱</span>")

                bf_done0 = int(r.get("meal_bf_done") or 0)
                lu_done0 = int(r.get("meal_lu_done") or 0)
                di_done0 = int(r.get("meal_di_done") or 0)
                if bf_done0 == 1 and int(r.get("meal_bf_score") or 0) <= 3:
                    badges.append("<span class='reaction-chip' style='border-color:rgba(180,83,9,0.25);background:rgba(180,83,9,0.10);'>🍽️ 朝 低摂取</span>")
                if lu_done0 == 1 and int(r.get("meal_lu_score") or 0) <= 3:
                    badges.append("<span class='reaction-chip' style='border-color:rgba(180,83,9,0.25);background:rgba(180,83,9,0.10);'>🍽️ 昼 低摂取</span>")
                if di_done0 == 1 and int(r.get("meal_di_score") or 0) <= 3:
                    badges.append("<span class='reaction-chip' style='border-color:rgba(180,83,9,0.25);background:rgba(180,83,9,0.10);'>🍽️ 夕 低摂取</span>")

                badges_html = "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;'>" + "".join(badges) + "</div>" if badges else ""

                # vitals small display (reuse builder)
                vitals_html = build_vital_section(r)

                scene_note2 = (r.get("scene_note") or "").strip()
                scene_note_html = ""
                if scene_note2:
                    scene_note_html = (
                        "<div style='margin-top:10px;"
                        "padding:10px 12px;border-radius:14px;"
                        "border:1px solid rgba(15,23,42,0.10);"
                        "background:rgba(15,23,42,0.02);"
                        "font-size:13px;line-height:1.55;'>"
                        f"<b>場面メモ：</b>{scene_note2}"
                        "</div>"
                    )

                note_head = str(r.get("note_head") or "")
                if len(note_head) > 0:
                    note_html = (
                        "<div style='margin-top:10px;color:var(--danger);font-size:13px;line-height:1.55;font-weight:900;'>"
                        f"<b>特記事項：</b>{note_head}</div>"
                    )
                else:
                    note_html = "<div style='margin-top:10px;color:var(--muted);font-size:12px;'>（特記事項なし）</div>"

                patrol_inline = build_patrol_inline(conn, rid) if patrol_count > 0 else ""

                st.markdown('<div class="record-card">', unsafe_allow_html=True)

                left, right = st.columns([9, 1])
                with left:
                    st.markdown(
                        f"""
<div class="header-row" style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;">
  <div class="h-main" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
    <span style="font-size:18px;font-weight:1000;letter-spacing:.3px;color:var(--accent2);">{t}</span>
    <span style="font-size:13px;font-weight:900;padding:4px 10px;border-radius:999px;border:1px solid var(--border);background:rgba(37,99,235,0.08);">{scene}</span>
    <span style="font-size:13px;font-weight:900;">記録者：{r['recorder_name']}</span>
    {patrol_badge}
  </div>
  <div style="font-size:12px;color:rgba(15,23,42,0.72);text-align:right;line-height:1.28;white-space:nowrap;">{meta_html}</div>
</div>
{badges_html}
{vitals_html}
{scene_note_html}
{note_html}
{patrol_inline}
                        """,
                        unsafe_allow_html=True,
                    )

                with right:
                    if st.button("削除", key=f"del_btn_{rid}"):
                        soft_delete_record(conn, rid)
                        try:
                            st.toast("🗑️ 削除しました（論理削除）")
                        except Exception:
                            st.success("削除しました（論理削除）。")
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------
    # Handover tab
    # -------------------------
    with tab_handover:
        st.subheader(f"🗒️ 申し送り（{unit_name} / {target_date_str}）")
        st.caption("⑥ 特記事項が保存されると、ここにも自動で反映されます。👍 いいねで「誰がいつ確認したか」を可視化できます。")

        if recorder_name.strip() == "":
            st.warning("サイドバーで「記録者名」を入力すると、👍 いいね履歴（誰がいつ）が残せます。")

        ho = list_handovers(conn, unit_id=unit_id, handover_date=target_date_str)
        if ho.empty:
            st.info("この日の申し送りはまだありません。")
        else:
            # resident name map
            res_map = {int(r["id"]): str(r["name"]) for _, r in residents_df.iterrows()}
            for _, h in ho.iterrows():
                hid = int(h["id"])
                rid = safe_int(h.get("resident_id"))
                who = str(h.get("created_by") or "")
                content = str(h.get("content") or "").strip()
                created_at = fmt_dt(h.get("created_at"))

                rname = res_map.get(int(rid), "（全体）") if rid is not None else "（全体）"

                reacts = list_reactions(conn, hid)


                likes = reacts.loc[reacts["reaction_type"] == "like"].copy() if not reacts.empty else pd.DataFrame(columns=["user_name","reaction_type","created_at"])


                like_count = int(len(likes))


                liked_by_me = False


                if recorder_name.strip() != "":


                    liked_by_me = has_reaction(conn, handover_id=hid, user_name=recorder_name.strip(), reaction_type="like")



                st.markdown('<div class="handover-card">', unsafe_allow_html=True)


                st.markdown(f"**{rname}**  \n{content}")


                st.markdown(f"<div class='handover-meta'>投稿：{created_at}｜投稿者：{who}</div>", unsafe_allow_html=True)



                like_label = f"👍 {like_count}"


                if liked_by_me:


                    like_label += "（あなた）"


                st.markdown(f"<div class='handover-meta' style='font-weight:900;'>{like_label}</div>", unsafe_allow_html=True)



                b1, b2 = st.columns([2.2, 7.8])


                with b1:


                    btn_txt = "👍 いいね" if not liked_by_me else "👍 いいね済み（取り消し）"


                    if st.button(btn_txt, key=f"ho_like_{hid}"):


                        if recorder_name.strip() != "":


                            toggle_reaction(conn, handover_id=hid, user_name=recorder_name.strip(), reaction_type="like")


                            st.rerun()


                        else:


                            st.warning("サイドバーで『記録者名』を入力すると、いいね履歴（誰がいつ）が残せます。")


                with b2:


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
