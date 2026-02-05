# app.py
# ============================================================
# グループホーム向け 介護記録アプリ（Streamlit + SQLite）
#
# ✅ 監査対応（時系列の証跡保持）
#   - 保存は常に INSERT（UPDATE/上書きはしない）
#   - 削除は論理削除（is_deleted=1）
#
# ✅ StreamlitAPIException 根絶（epoch方式）
#   - 入力ウィジェット key に epoch を付与
#   - 保存成功後は epoch++ → st.rerun() で安全に全入力初期化
#   - 保存後に st.session_state[widget_key] を直接書き換えない
#
# ✅ UI/UX
#   - ①支援記録：時・分・場面・内容・申し送り を横一列（PC）に調整
#   - 履歴：特記事項(note)があるレコードは赤文字＋要確認バッジ
#   - 申し送りボード：黒文字（コピペ最優先）＋確認ボタン（DB記録）
#
# ✅ クラウド用DBパス対応
#   - secrets / env から DB_PATH を取得可能
#   - ただし Streamlit Community Cloud のローカルファイルは永続保証が弱いので
#     本当に「消えない」運用には外部ストレージ/DB推奨 :contentReference[oaicite:1]{index=1}
#
# インストール:
#   python -m pip install -r requirements.txt
# 起動:
#   streamlit run app.py
# ============================================================

import os
import sqlite3
import html as _html
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
      1) st.secrets["DB_PATH"] があればそれ
      2) 環境変数 TOMOGAKI_DB_PATH / DB_PATH があればそれ
      3) アプリ配下 data/tomogaki_proto.db
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
        # ディレクトリ指定ならファイル名を補完
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

    # added fields
    ensure_column(conn, "daily_records", "scene_note", "scene_note TEXT")

    # ✅ 申し送り（重要フラグ）＆確認済みフラグ（監査用の証跡としても有用）
    ensure_column(conn, "daily_records", "is_report", "is_report INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "daily_records", "is_confirmed", "is_confirmed INTEGER NOT NULL DEFAULT 0")

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


# -------------------------
# safe number conversion
# -------------------------
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


def esc(s: str) -> str:
    return _html.escape(s, quote=True)


def to_html_lines(s: str) -> str:
    return esc(s).replace("\n", "<br>")


def build_vital_inline(row) -> str:
    parts = []

    # 朝
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

    # 夕
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
# Snapshot（当日の最新入力値） / Named placeholders
# -------------------------
def get_day_snapshot_for_resident(conn, resident_id: int, target_date: str):
    params = {"resident_id": int(resident_id), "target_date": str(target_date)}
    sql = """
    WITH base AS (
      SELECT *
        FROM daily_records
       WHERE resident_id=:resident_id
         AND record_date=:target_date
         AND is_deleted=0
    ),
    last_temp_am AS (
      SELECT temp_am AS v FROM base
       WHERE temp_am IS NOT NULL AND temp_am != 0
       ORDER BY updated_at DESC, id DESC LIMIT 1
    ),
    last_temp_pm AS (
      SELECT temp_pm AS v FROM base
       WHERE temp_pm IS NOT NULL AND temp_pm != 0
       ORDER BY updated_at DESC, id DESC LIMIT 1
    ),
    last_bf AS (
      SELECT meal_bf_score AS v FROM base
       WHERE meal_bf_done=1 AND meal_bf_score > 0
       ORDER BY updated_at DESC, id DESC LIMIT 1
    ),
    last_lu AS (
      SELECT meal_lu_score AS v FROM base
       WHERE meal_lu_done=1 AND meal_lu_score > 0
       ORDER BY updated_at DESC, id DESC LIMIT 1
    ),
    last_di AS (
      SELECT meal_di_score AS v FROM base
       WHERE meal_di_done=1 AND meal_di_score > 0
       ORDER BY updated_at DESC, id DESC LIMIT 1
    ),
    meds AS (
      SELECT
        MAX(med_morning) AS m,
        MAX(med_noon)    AS n,
        MAX(med_evening) AS e,
        MAX(med_bed)     AS b
      FROM base
    ),
    patrols AS (
      SELECT p.patrol_time_hh, p.patrol_time_mm, p.status
        FROM daily_patrols p
        JOIN daily_records r ON r.id = p.record_id
       WHERE r.resident_id=:resident_id
         AND r.record_date=:target_date
         AND r.is_deleted=0
       ORDER BY
         (p.patrol_time_hh IS NULL),
         p.patrol_time_hh DESC,
         p.patrol_time_mm DESC,
         p.id DESC
       LIMIT 1
    ),
    patrol_count AS (
      SELECT COUNT(1) AS c
        FROM daily_patrols p
        JOIN daily_records r ON r.id = p.record_id
       WHERE r.resident_id=:resident_id
         AND r.record_date=:target_date
         AND r.is_deleted=0
    )
    SELECT
      (SELECT v FROM last_temp_am) AS temp_am,
      (SELECT v FROM last_temp_pm) AS temp_pm,
      (SELECT v FROM last_bf) AS bf_score,
      (SELECT v FROM last_lu) AS lu_score,
      (SELECT v FROM last_di) AS di_score,
      (SELECT m FROM meds) AS med_m,
      (SELECT n FROM meds) AS med_n,
      (SELECT e FROM meds) AS med_e,
      (SELECT b FROM meds) AS med_b,
      (SELECT c FROM patrol_count) AS patrol_count,
      (SELECT patrol_time_hh FROM patrols) AS last_patrol_hh,
      (SELECT patrol_time_mm FROM patrols) AS last_patrol_mm,
      (SELECT status FROM patrols) AS last_patrol_status
    """
    df = fetch_df(conn, sql, params=params)
    if df.empty:
        return None
    return df.loc[0].to_dict()


def build_resident_subtext(snapshot: dict) -> str:
    if not snapshot:
        return "未入力 / 体温: -- / 食事: -- / 服薬: -- / 巡視: 0回"

    # 体温表示
    ta = safe_float(snapshot.get("temp_am"))
    tp = safe_float(snapshot.get("temp_pm"))
    if ta is not None and tp is not None:
        temp_txt = "体温: 朝OK/夕OK"
    else:
        ta_txt = "--" if ta is None else f"{ta:.1f}"
        tp_txt = "--" if tp is None else f"{tp:.1f}"
        temp_txt = f"体温: 朝{ta_txt}/夕{tp_txt}"

    # 食事
    meals = []
    bf = safe_int(snapshot.get("bf_score"))
    lu = safe_int(snapshot.get("lu_score"))
    di = safe_int(snapshot.get("di_score"))
    if bf:
        meals.append(f"朝{bf}")
    if lu:
        meals.append(f"昼{lu}")
    if di:
        meals.append(f"夕{di}")
    meal_txt = "食事: " + (" ".join(meals) if meals else "--")

    # 服薬
    meds = []
    if safe_int(snapshot.get("med_m")) == 1:
        meds.append("朝OK")
    if safe_int(snapshot.get("med_n")) == 1:
        meds.append("昼OK")
    if safe_int(snapshot.get("med_e")) == 1:
        meds.append("夕OK")
    if safe_int(snapshot.get("med_b")) == 1:
        meds.append("寝OK")
    med_txt = "服薬: " + ("/".join(meds) if meds else "--")

    # 巡視
    pc = safe_int(snapshot.get("patrol_count")) or 0
    last_hh = snapshot.get("last_patrol_hh")
    last_mm = snapshot.get("last_patrol_mm")
    if pc > 0 and safe_int(last_hh) is not None and safe_int(last_mm) is not None:
        last_t = hhmm(last_hh, last_mm)
        last_s = (snapshot.get("last_patrol_status") or "").strip() or "記載なし"
        patrol_txt = f"巡視: {pc}回（最終 {last_t} {last_s}）"
    else:
        patrol_txt = f"巡視: {pc}回"

    return " / ".join([temp_txt, meal_txt, med_txt, patrol_txt])


# -------------------------
# Records / Patrols
# -------------------------
def insert_record(conn, payload: dict, patrols: list):
    """監査対応：常に INSERT（UPDATEしない）"""
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
    # ✅ 昇順（0:00→23:55）、同時刻は id 昇順
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
  --shadow: 0 10px 26px rgba(17,24,39,0.08);
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
.record-card:hover{ box-shadow: var(--shadow); transition: 160ms ease; }

/* 履歴：要注意（特記事項あり） */
.record-alert{
  border-color: rgba(225,29,72,0.35);
  background: rgba(225,29,72,0.03);
}
.record-alert .meta,
.record-alert .vital-line,
.record-alert .note-box{
  color: var(--danger) !important;
}
.record-alert .note-box b,
.record-alert .meta b{
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
.badge-warn{ background: rgba(245,158,11,0.14); border-color: rgba(245,158,11,0.30); }
.badge-danger{ background: rgba(225,29,72,0.12); border-color: rgba(225,29,72,0.28); color: var(--danger); }

.meta{
  color: rgba(17,24,39,0.60);
  font-size: 12px;
  font-weight: 800;
}
.meta-small{
  color: rgba(17,24,39,0.62);
  font-size: 11.5px;
  font-weight: 700;
}

.vital-line{
  font-size: 12.5px;
  color: rgba(17,24,39,0.86);
  margin-top: 6px;
}
.vital-alert{ color: var(--danger); font-weight: 900; }

.note-box{
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.45;
  color: rgba(17,24,39,0.92);
  white-space: pre-wrap;
}

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
.big-save .stButton > button:hover{
  filter: brightness(0.98);
  transform: translateY(-1px);
  transition: 120ms ease;
}

/* 申し送りボード枠 */
.report-board{
  background: #fff7cc;
  border: 1px solid rgba(245,158,11,0.35);
  border-radius: 16px;
  padding: 12px 14px;
  box-shadow: var(--shadow2);
}

section[data-testid="stSidebar"]{
  border-right: 1px solid var(--border);
  background: #ffffff;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input{
  background: #fff7cc !important;
  border: 2px solid var(--warn) !important;
  border-radius: 10px !important;
  font-weight: 800 !important;
}
[data-testid="stCaptionContainer"]{ color: var(--muted); }
</style>
        """,
        unsafe_allow_html=True,
    )


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
# Monthly helpers
# -------------------------
def month_range(year: int, month: int):
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return first, last


# -------------------------
# Pages
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

    if recorder_name.strip() == "":
        st.sidebar.warning("⚠ 記録者名が未入力です。保存できません。")

    st.title("📝 介護記録（監査対応 / 時系列保持）")
    st.caption(f"DB: {DB_PATH}（保存は常にINSERT／削除は論理削除）")

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
        snap = get_day_snapshot_for_resident(conn, rid, target_date_str)
        sub = build_resident_subtext(snap)

        c = cols[idx % 3]
        with c:
            st.markdown(
                f"""
<div class="record-card">
  <div class="section-title">{esc(nm)}</div>
  <div class="section-sub">{esc(sub)}</div>
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

    # ① 支援記録（横一列最適化）
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">① 支援記録（時刻・場面）</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">場面が未選択以外のとき「記録内容（フリーワード）」を表示します。申し送りONはボードに抽出されます。</div>', unsafe_allow_html=True)

        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 4, 1.5])
        with c1:
            add_hh = st.selectbox("時", hh_options, index=0, key=wkey("add_time_hh"))
        with c2:
            add_mm = st.selectbox("分", mm_options, index=0, key=wkey("add_time_mm"))
        with c3:
            add_scene = st.selectbox(
                "場面",
                SCENES,
                index=SCENES.index("ご様子"),
                format_func=scene_display,
                key=wkey("add_scene"),
            )
        with c4:
            if add_scene != "":
                scene_note = st.text_input(
                    "内容（短文）",
                    value="",
                    key=wkey("scene_note"),
                    placeholder="例：声かけで落ち着く／不穏あり等（短文）",
                )
            else:
                scene_note = ""
        with c5:
            is_report = st.checkbox("重要：申し送り", value=False, key=wkey("is_report"))

        st.markdown("</div>", unsafe_allow_html=True)

    # ② バイタル
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">② バイタル（朝・夕）</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">未入力は 0 のままでOK（保存時に NULL 化）。一覧表示では 0/NULL は表示しません。</div>', unsafe_allow_html=True)

        st.markdown("**朝**")
        v1, v2, v3, v4, v5 = st.columns(5)
        with v1:
            am_temp = st.number_input("体温（℃）", value=0.0, step=0.1, format="%.1f", key=wkey("am_temp"))
        with v2:
            am_sys = st.number_input("血圧 上", value=0, step=1, key=wkey("am_sys"))
        with v3:
            am_dia = st.number_input("血圧 下", value=0, step=1, key=wkey("am_dia"))
        with v4:
            am_pulse = st.number_input("脈拍", value=0, step=1, key=wkey("am_pulse"))
        with v5:
            am_spo2 = st.number_input("SpO₂", value=0, step=1, key=wkey("am_spo2"))

        st.markdown("**夕**")
        w1, w2, w3, w4, w5 = st.columns(5)
        with w1:
            pm_temp = st.number_input("体温（℃） ", value=0.0, step=0.1, format="%.1f", key=wkey("pm_temp"))
        with w2:
            pm_sys = st.number_input("血圧 上 ", value=0, step=1, key=wkey("pm_sys"))
        with w3:
            pm_dia = st.number_input("血圧 下 ", value=0, step=1, key=wkey("pm_dia"))
        with w4:
            pm_pulse = st.number_input("脈拍 ", value=0, step=1, key=wkey("pm_pulse"))
        with w5:
            pm_spo2 = st.number_input("SpO₂ ", value=0, step=1, key=wkey("pm_spo2"))

        st.markdown("</div>", unsafe_allow_html=True)

    # ③ 食事
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">③ 食事（即時反応）</div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        with m1:
            bf_done = st.toggle("朝食あり", value=False, key=wkey("bf_done"))
            bf_score = st.slider("朝食量（1〜10）", 1, 10, value=5, key=wkey("bf_score"), disabled=(not bf_done))
        with m2:
            lu_done = st.toggle("昼食あり", value=False, key=wkey("lu_done"))
            lu_score = st.slider("昼食量（1〜10）", 1, 10, value=5, key=wkey("lu_score"), disabled=(not lu_done))
        with m3:
            di_done = st.toggle("夕食あり", value=False, key=wkey("di_done"))
            di_score = st.slider("夕食量（1〜10）", 1, 10, value=5, key=wkey("di_score"), disabled=(not di_done))

        st.markdown("</div>", unsafe_allow_html=True)

    # ④ 服薬
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">④ 服薬</div>', unsafe_allow_html=True)

        a, b, c, d = st.columns(4)
        with a:
            med_m = st.checkbox("朝", value=False, key=wkey("med_m"))
        with b:
            med_n = st.checkbox("昼", value=False, key=wkey("med_n"))
        with c:
            med_e = st.checkbox("夕", value=False, key=wkey("med_e"))
        with d:
            med_b = st.checkbox("寝る前", value=False, key=wkey("med_b"))

        st.markdown("</div>", unsafe_allow_html=True)

    # ⑤ 巡視
    patrol_list = []
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⑤ 巡視（チェックで即表示）</div>', unsafe_allow_html=True)

        enable_patrol = st.checkbox("巡視を記録する", value=False, key=wkey("enable_patrol"))

        if enable_patrol:
            pcol1, pcol2 = st.columns(2)

            def patrol_block(no: int, col):
                with col:
                    st.markdown(f"**巡視{no}**")
                    ph = st.selectbox("時", hh_options, index=0, key=wkey(f"p{no}_hh"))
                    pm = st.selectbox("分", mm_options, index=0, key=wkey(f"p{no}_mm"))
                    ps = st.selectbox("状況", PATROL_STATUS_OPTIONS, index=0, key=wkey(f"p{no}_status"))
                    pmemo = st.text_input("メモ", value="", key=wkey(f"p{no}_memo"))
                    pint = st.checkbox("対応した", value=False, key=wkey(f"p{no}_int"))
                    pdoor = st.checkbox("居室ドアを開けた", value=False, key=wkey(f"p{no}_door"))
                    psafety = st.multiselect("安全チェック", SAFETY_OPTIONS, default=[], key=wkey(f"p{no}_safety"))

                    has_any = (
                        (ph != "未選択" and pm != "未選択")
                        or (ps or "").strip() != ""
                        or (pmemo or "").strip() != ""
                        or pint
                        or pdoor
                        or len(psafety) > 0
                    )
                    if not has_any:
                        return None

                    return {
                        "patrol_no": no,
                        "patrol_time_hh": None if ph == "未選択" else safe_int(ph),
                        "patrol_time_mm": None if pm == "未選択" else safe_int(pm),
                        "status": ps,
                        "memo": pmemo,
                        "intervened": 1 if pint else 0,
                        "door_opened": 1 if pdoor else 0,
                        "safety_checks": ",".join(psafety),
                    }

            p1 = patrol_block(1, pcol1)
            p2 = patrol_block(2, pcol2)
            if p1:
                patrol_list.append(p1)
            if p2:
                patrol_list.append(p2)

        st.markdown("</div>", unsafe_allow_html=True)

    # ⑥ 特記事項 + 下部保存
    with st.container():
        st.markdown('<div class="record-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⑥ 特記事項（普段と行動が違う等）</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">いつもと違う様子や、特記すべき事項を詳細に記入してください。</div>', unsafe_allow_html=True)

        note = st.text_area(
            "特記事項（詳細）",
            value="",
            height=260,
            key=wkey("note"),
            placeholder="例：いつもと違う行動／不穏／対応／結果／引き継ぎ事項 など",
        )

        st.markdown('<div class="big-save">', unsafe_allow_html=True)
        bottom_save_clicked = st.button("保存して記録を追加", key="bottom_save_btn", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # 保存（巡視だけでも保存できるようにする）
    save_clicked = top_save_clicked or bottom_save_clicked
    if save_clicked:
        if recorder_name.strip() == "":
            st.error("記録者名（必須）を入力してください。")
        else:
            # 親レコードの時刻決定：
            # ①が選択済みならそれを採用
            # ①未選択で巡視ONなら、巡視1回目（最小 patrol_no）の時刻をコピー
            chosen_hh = None
            chosen_mm = None
            if add_hh != "未選択" and add_mm != "未選択":
                chosen_hh = safe_int(add_hh)
                chosen_mm = safe_int(add_mm)
            else:
                # 巡視がある場合は、時刻が入っている最初の巡視を探す
                if patrol_list:
                    # patrol_no昇順
                    p_sorted = sorted(patrol_list, key=lambda x: safe_int(x.get("patrol_no")) or 9999)
                    for p in p_sorted:
                        ph = safe_int(p.get("patrol_time_hh"))
                        pm = safe_int(p.get("patrol_time_mm"))
                        if ph is not None and pm is not None:
                            chosen_hh, chosen_mm = ph, pm
                            break

            if chosen_hh is None or chosen_mm is None:
                st.error("時刻（①の時/分 または ⑤巡視の時/分）を入力してください。")
            else:
                def n_real(x):
                    f = safe_float(x)
                    return None if (f is None or abs(f) < 1e-12) else float(f)

                def n_int(x):
                    i = safe_int(x)
                    return None if (i is None or i == 0) else int(i)

                payload = {
                    "unit_id": unit_id,
                    "resident_id": int(selected),
                    "record_date": target_date_str,
                    "record_time_hh": chosen_hh,
                    "record_time_mm": chosen_mm,
                    "shift": shift,
                    "recorder_name": recorder_name.strip(),
                    "scene": add_scene if add_scene in SCENES else "ご様子",
                    "scene_note": (scene_note or "").strip(),

                    "temp_am": n_real(am_temp),
                    "bp_sys_am": n_int(am_sys),
                    "bp_dia_am": n_int(am_dia),
                    "pulse_am": n_int(am_pulse),
                    "spo2_am": n_int(am_spo2),

                    "temp_pm": n_real(pm_temp),
                    "bp_sys_pm": n_int(pm_sys),
                    "bp_dia_pm": n_int(pm_dia),
                    "pulse_pm": n_int(pm_pulse),
                    "spo2_pm": n_int(pm_spo2),

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

                    "note": (note or "").strip(),
                    "is_report": 1 if is_report else 0,
                    "is_confirmed": 0,
                }

                record_id = insert_record(conn, payload, patrol_list)
                bump_add_epoch_and_rerun(f"✅ 記録を保存しました（ID: {record_id}）")

    st.divider()

    # -------------------------
    # 申し送りボード（黒文字・コピペ用・確認ボタン付き）
    # -------------------------
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

            # 表示（黒文字）＋確認ボタン
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

    # -------------------------
    # 履歴（スクロール枠）— 特記事項は赤文字
    # -------------------------
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

            # 特記事項判定（空や None は除外）
            note_txt_raw = (str(r.get("note") or "")).strip()
            has_note = (note_txt_raw != "")

            # badges
            badges = []
            meds_any = (
                (safe_int(r.get("med_morning")) == 1)
                or (safe_int(r.get("med_noon")) == 1)
                or (safe_int(r.get("med_evening")) == 1)
                or (safe_int(r.get("med_bed")) == 1)
            )
            if meds_any:
                badges.append("✅服薬OK")

            if safe_int(r.get("is_report")) == 1:
                badges.append("📋申し送り")

            if has_note:
                badges.append("要確認")

            # patrol
            patrol_count = safe_int(r.get("patrol_count")) or 0
            patrol_badge = (
                f"<span class='badge badge-ok'>✅ 巡視({patrol_count}回)</span>" if patrol_count > 0 else ""
            )

            title = f"{t} / {scene_display(r.get('scene'))} / 記録者：{r.get('recorder_name')}"
            if (str(r.get("scene_note") or "")).strip():
                title += f" <span class='badge badge-warn'>短記録</span>"

            vital_inline = build_vital_inline(r)

            card_class = "record-card record-alert" if has_note else "record-card"
            st.markdown(f"<div class='{card_class}'>", unsafe_allow_html=True)

            h1, h2 = st.columns([8, 2])
            with h1:
                # バッジはHTMLで安全に描画（タグ露出対策：unsafe_allow_html=True）
                badge_txt = ""
                if badges:
                    b_html = " ".join([f"<span class='badge badge-danger'>{esc(x)}</span>" if x in ["要確認"] else f"<span class='badge badge-ok'>{esc(x)}</span>" for x in badges])
                    badge_txt = b_html
                st.markdown(
                    f"<div class='meta'><b>{esc(title)}</b> {badge_txt} {patrol_badge}</div>",
                    unsafe_allow_html=True,
                )
            with h2:
                if st.button("🗑️ 削除", key=f"del_{rec_id}", use_container_width=True):
                    soft_delete_record(conn, rec_id)
                    st.session_state["__toast__"] = "🗑️ 記録を削除（論理削除）しました"
                    st.rerun()

            # scene_note
            scene_note_txt = (str(r.get("scene_note") or "")).strip()
            if scene_note_txt:
                st.markdown(
                    f"<div class='vital-line'>■ 記録内容（短文）：{to_html_lines(scene_note_txt)}</div>",
                    unsafe_allow_html=True,
                )

            # vitals
            if vital_inline:
                cls = "vital-line"
                ta = safe_float(r.get("temp_am"))
                tp = safe_float(r.get("temp_pm"))
                if (ta is not None and ta >= 37.5) or (tp is not None and tp >= 37.5):
                    cls = "vital-line vital-alert"
                st.markdown(f"<div class='{cls}'>■ バイタル：{esc(vital_inline)}</div>", unsafe_allow_html=True)

            # meals
            meals = []
            if safe_int(r.get("meal_bf_done")) == 1 and (safe_int(r.get("meal_bf_score")) or 0) > 0:
                meals.append(f"朝{safe_int(r.get('meal_bf_score'))}")
            if safe_int(r.get("meal_lu_done")) == 1 and (safe_int(r.get("meal_lu_score")) or 0) > 0:
                meals.append(f"昼{safe_int(r.get('meal_lu_score'))}")
            if safe_int(r.get("meal_di_done")) == 1 and (safe_int(r.get("meal_di_score")) or 0) > 0:
                meals.append(f"夕{safe_int(r.get('meal_di_score'))}")
            if meals:
                st.markdown(f"<div class='vital-line'>■ 食事：{esc(' / '.join(meals))}</div>", unsafe_allow_html=True)

            # patrol inline
            if patrol_count > 0:
                pdf = load_patrols(conn, rec_id)
                if not pdf.empty:
                    lines = []
                    for _, p in pdf.iterrows():
                        pt = hhmm(p.get("patrol_time_hh"), p.get("patrol_time_mm"))
                        stt = (p.get("status") or "").strip() or "記載なし"
                        saf = (p.get("safety_checks") or "").strip()
                        saf_txt = f" / 安全:{saf}" if saf else ""
                        lines.append(f"巡視{safe_int(p.get('patrol_no')) or 0} {pt} {stt}{saf_txt}")
                    st.markdown(f"<div class='vital-line'>■ 巡視：{esc(' ｜ '.join(lines))}</div>", unsafe_allow_html=True)

            # note（特記事項）
            if has_note:
                st.markdown(
                    f"<div class='note-box'><b>■ 特記事項：</b><br>{to_html_lines(note_txt_raw)}</div>",
                    unsafe_allow_html=True,
                )

            # timestamps
            created = str(r.get("created_at") or "")
            updated = str(r.get("updated_at") or "")
            st.markdown(
                f"<div class='meta-small' style='text-align:right;'>作成: {esc(created)}　/　更新: {esc(updated)}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)


def page_monthly(conn):
    maybe_toast()

    st.title("📅 月次集計・印刷（請求対応）")
    st.caption("選択した年月のデータを抽出し、食事提供数集計と日付順の一覧を表示します（Ctrl+Pで印刷）。")

    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット（集計）", units_df["name"].tolist(), index=0, key="m_unit")
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    residents_df = fetch_df(
        conn,
        "SELECT id, name FROM residents WHERE unit_id=:uid AND is_active=1 ORDER BY name;",
        {"uid": unit_id},
    )
    if residents_df.empty:
        st.info("利用者がいません。")
        return

    rid = st.selectbox(
        "利用者",
        residents_df["id"].tolist(),
        format_func=lambda x: residents_df.loc[residents_df["id"] == x, "name"].iloc[0],
        key="m_res",
    )

    y1, y2 = st.columns(2)
    with y1:
        year = int(st.number_input("年", value=date.today().year, min_value=2000, max_value=2100, step=1, key="m_year"))
    with y2:
        month = int(st.number_input("月", value=date.today().month, min_value=1, max_value=12, step=1, key="m_month"))

    first, last = month_range(year, month)

    df = fetch_df(
        conn,
        """
        SELECT record_date, record_time_hh, record_time_mm, shift, recorder_name, scene, scene_note, note,
               meal_bf_done, meal_lu_done, meal_di_done
          FROM daily_records
         WHERE resident_id=:rid
           AND record_date >= :d1 AND record_date <= :d2
           AND is_deleted=0
         ORDER BY record_date ASC, (record_time_hh IS NULL), record_time_hh ASC, record_time_mm ASC, id ASC
        """,
        {"rid": int(rid), "d1": first.isoformat(), "d2": last.isoformat()},
    )

    if df.empty:
        st.info("対象月の記録がありません。")
        return

    bf_cnt = int((df["meal_bf_done"] == 1).sum())
    lu_cnt = int((df["meal_lu_done"] == 1).sum())
    di_cnt = int((df["meal_di_done"] == 1).sum())
    meal_sum = pd.DataFrame([{"朝食 提供数": bf_cnt, "昼食 提供数": lu_cnt, "夕食 提供数": di_cnt}])
    st.markdown("### 🍽️ 食事提供数（カウント）")
    st.dataframe(meal_sum, use_container_width=True, hide_index=True)

    st.markdown("### 📄 支援記録（印刷向け一覧）")
    out = df.copy()
    out["時刻"] = out.apply(lambda r: hhmm(r.get("record_time_hh"), r.get("record_time_mm")), axis=1)
    out["場面"] = out["scene"].fillna("").map(scene_display)
    out["短文"] = out["scene_note"].fillna("").astype(str)
    out["特記事項"] = out["note"].fillna("").astype(str)

    out2 = out[["record_date", "時刻", "場面", "recorder_name", "短文", "特記事項"]].rename(
        columns={"record_date": "日付", "recorder_name": "記録者"}
    )
    st.dataframe(out2, use_container_width=True, hide_index=True)

    csv = out2.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSVダウンロード（Excel向け）",
        data=csv,
        file_name=f"monthly_{int(rid)}_{first.strftime('%Y-%m')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.markdown("---")
    st.write("印刷のコツ：Ctrl+P → 余白「狭い」、ヘッダー/フッターOFF、縮尺 85〜90% が綺麗です。")


def page_graph(conn):
    maybe_toast()

    st.title("📈 バイタルグラフ")
    st.caption("選択期間の体温・血圧（上/下）推移を表示します。未入力日は点が飛ぶように（欠損として）処理します。")

    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット（グラフ）", units_df["name"].tolist(), index=0, key="g_unit")
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    residents_df = fetch_df(
        conn,
        "SELECT id, name FROM residents WHERE unit_id=:uid AND is_active=1 ORDER BY name;",
        {"uid": unit_id},
    )
    if residents_df.empty:
        st.info("利用者がいません。")
        return

    rid = st.selectbox(
        "利用者",
        residents_df["id"].tolist(),
        format_func=lambda x: residents_df.loc[residents_df["id"] == x, "name"].iloc[0],
        key="g_res",
    )

    today = date.today()
    c1, c2 = st.columns(2)
    with c1:
        start = st.date_input("開始日", value=today - timedelta(days=30), key="g_start")
    with c2:
        end = st.date_input("終了日", value=today, key="g_end")

    df = fetch_df(
        conn,
        """
        SELECT record_date, record_time_hh, record_time_mm,
               temp_am, temp_pm, bp_sys_am, bp_dia_am, bp_sys_pm, bp_dia_pm
          FROM daily_records
         WHERE resident_id=:rid
           AND record_date >= :d1 AND record_date <= :d2
           AND is_deleted=0
         ORDER BY record_date ASC, (record_time_hh IS NULL), record_time_hh ASC, record_time_mm ASC, id ASC
        """,
        {"rid": int(rid), "d1": start.isoformat(), "d2": end.isoformat()},
    )

    if df.empty:
        st.info("対象期間のデータがありません。")
        return

    days = pd.date_range(start=start, end=end, freq="D")
    out = pd.DataFrame(index=days)

    df2 = df.copy()
    df2["d"] = pd.to_datetime(df2["record_date"]).dt.date

    def last_nonzero(series):
        for v in reversed(series.tolist()):
            f = safe_float(v)
            if f is None or abs(f) < 1e-12:
                continue
            return f
        return None

    def last_bp(series_sys, series_dia):
        for s, d in zip(reversed(series_sys.tolist()), reversed(series_dia.tolist())):
            si = safe_int(s)
            di = safe_int(d)
            if si and di:
                return si, di
        return None, None

    for d, g in df2.groupby("d"):
        dt = pd.Timestamp(d)
        ta = last_nonzero(g["temp_am"])
        tp = last_nonzero(g["temp_pm"])
        out.loc[dt, "体温(朝)"] = ta if ta is not None else float("nan")
        out.loc[dt, "体温(夕)"] = tp if tp is not None else float("nan")

        sys_am, dia_am = last_bp(g["bp_sys_am"], g["bp_dia_am"])
        sys_pm, dia_pm = last_bp(g["bp_sys_pm"], g["bp_dia_pm"])
        out.loc[dt, "血圧上(朝)"] = sys_am if sys_am else float("nan")
        out.loc[dt, "血圧下(朝)"] = dia_am if dia_am else float("nan")
        out.loc[dt, "血圧上(夕)"] = sys_pm if sys_pm else float("nan")
        out.loc[dt, "血圧下(夕)"] = dia_pm if dia_pm else float("nan")

    st.markdown("#### 体温推移")
    st.line_chart(out[["体温(朝)", "体温(夕)"]], use_container_width=True)

    st.markdown("#### 血圧推移")
    st.line_chart(out[["血圧上(朝)", "血圧下(朝)", "血圧上(夕)", "血圧下(夕)"]], use_container_width=True)

    st.markdown("---")
    st.write("印刷のコツ：Ctrl+P → 縮尺 85〜90% が綺麗です。")


# -------------------------
# main
# -------------------------
def main():
    st.set_page_config(page_title="介護記録（監査対応）", layout="wide")
    inject_css()

    conn = get_conn()
    init_db(conn)

    feature = st.sidebar.selectbox("機能選択", ["日次記録", "月次集計・印刷", "バイタルグラフ"], index=0)

    if feature == "日次記録":
        page_daily(conn)
    elif feature == "月次集計・印刷":
        page_monthly(conn)
    else:
        page_graph(conn)

    conn.close()


if __name__ == "__main__":
    main()
