# app.py
# ============================================================
# グループホーム向け 介護記録アプリ（Streamlit + SQLite）
# Mobile First / 1カラム最適化版（2026-02）
#
# ✅ 主な仕様
# - 4タブ: 「入力」「経過一覧」「申し送り」「印刷用出力（週報）」
# - 入力は基本1カラム（st.columnsを多用しない）
# - 時刻入力の二度手間を廃止
#    * 巡視がある場合：最新（最大）の巡視時刻を主時刻として自動採用
#    * 巡視がない場合：現在時刻（5分丸め）を主時刻として自動採用
# - ⑥特記事項に1文字でも入力 or チェックON の間は赤強調（タイトル/保存ボタン/①見出し）
# - residents に kubun / disease を追加（AI分析の下地）
# - 申し送りは 👍 のみ（誰が押したかを表示、履歴も保持）
# - バイタルはデフォルト未入力（空欄）。入力して保存した項目だけ記録。
# - 週報（行政提出用）をCSV/Excel出力
# - サイドバーに全データバックアップ（CSV.zip）
#
# 起動:
#   py -m pip install streamlit pandas openpyxl
#   py -m streamlit run app.py
# ============================================================

import os
import sqlite3
import io
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import date, datetime, time as dtime, timezone, timedelta

import pandas as pd
import streamlit as st


# --- Timezone (JST) ---
JST = timezone(timedelta(hours=9))


# -------------------------
# Paths / DB
# -------------------------
def get_db_path() -> Path:
    # Streamlit Cloud や Windows で確実に書き込める場所に置く（read-only回避）
    env = os.environ.get("KAIGO_DB_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    home = Path.home()
    data_dir = home / ".kaigo_app_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "tomogaki_proto.db"


DB_PATH = get_db_path()


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON;")
    # ロック耐性
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def fetch_df(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def exec_sql(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return cur


def now_iso():
    return datetime.now(JST).isoformat(timespec="seconds")


def get_table_cols(conn, table: str) -> set:
    df = fetch_df(conn, f"PRAGMA table_info({table});")
    return set(df["name"].tolist()) if not df.empty else set()


def ensure_column(conn, table: str, col: str, col_def_sql: str):
    cols = get_table_cols(conn, table)
    if col not in cols:
        exec_sql(conn, f"ALTER TABLE {table} ADD COLUMN {col_def_sql};")


def update_resident_master(conn, *, resident_id: int, kubun: str, disease: str):
    """利用者マスタ（区分・症名）を更新する。列が無い場合も安全に追加してから更新する。"""
    ensure_column(conn, "residents", "kubun", "kubun TEXT")
    ensure_column(conn, "residents", "disease", "disease TEXT")
    exec_sql(
        conn,
        "UPDATE residents SET kubun=?, disease=? WHERE id=?",
        ((kubun or "").strip(), (disease or "").strip(), int(resident_id)),
    )


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

    # residents extra fields（AI連携の下地）
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
            scene_note TEXT,
            wakeup_flag INTEGER NOT NULL DEFAULT 0,

            temp_am REAL,
            bp_sys_am INTEGER,
            bp_dia_am INTEGER,
            pulse_am INTEGER,
            spo2_am INTEGER,

            temp_pm REAL,
            bp_sys_pm INTEGER,
            bp_dia_pm INTEGER,
            pulse_pm INTEGER,
            spo2_pm INTEGER,

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

    # 申し送り
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
            reaction_type TEXT NOT NULL, -- 'like'
            created_at TEXT NOT NULL,
            UNIQUE(handover_id, user_name, reaction_type),
            FOREIGN KEY(handover_id) REFERENCES handovers(id) ON DELETE CASCADE
        );
        """,
    )
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
            exec_sql(conn, "INSERT INTO residents(unit_id, name, kubun, disease) VALUES(?,?,?,?)", (unit_a, nm, "", ""))
        for nm in ["高橋 美咲", "伊藤 恒一"]:
            exec_sql(conn, "INSERT INTO residents(unit_id, name, kubun, disease) VALUES(?,?,?,?)", (unit_b, nm, "", ""))


# -------------------------
# Helpers
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


def parse_int_str(s: str):
    """Text input -> int or None (blank/invalid -> None)."""
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def parse_float_str(s: str):
    """Text input -> float or None (blank/invalid -> None)."""
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
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
        return "--:--"
    return f"{int(hh):02d}:{int(mm):02d}"


def round_now_5min():
    now = datetime.now(JST)
    minute = (now.minute // 5) * 5
    return now.replace(minute=minute, second=0, microsecond=0)


def latest_vitals_anyday(conn, resident_id: int):
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
    return df.loc[0].to_dict()


def list_records_for_day(conn, resident_id: int, target_date: str):
    # 経過一覧は「直近が上」＝降順
    return fetch_df(
        conn,
        """
        SELECT r.id,
               r.record_time_hh, r.record_time_mm,
               r.shift, r.recorder_name,
               r.scene, r.scene_note,
               r.temp_am, r.spo2_am, r.pulse_am, r.bp_sys_am, r.bp_dia_am,
               r.temp_pm, r.spo2_pm, r.pulse_pm, r.bp_sys_pm, r.bp_dia_pm,
               r.meal_bf_done, r.meal_bf_score,
               r.meal_lu_done, r.meal_lu_score,
               r.meal_di_done, r.meal_di_score,
               r.med_morning, r.med_noon, r.med_evening, r.med_bed,
               r.note,
               substr(r.note,1,240) AS note_head,
               r.created_at, r.updated_at,
               (SELECT COUNT(1) FROM daily_patrols p WHERE p.record_id=r.id) AS patrol_count
          FROM daily_records r
         WHERE r.resident_id=?
           AND r.record_date=?
           AND r.is_deleted=0
         ORDER BY
           (r.record_time_hh IS NULL) ASC,
           r.record_time_hh DESC,
           r.record_time_mm DESC,
           r.id DESC
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
# Export / Weekly report
# -------------------------
def export_all_tables_zip(conn) -> bytes:
    """全テーブルをCSVにしてzipで返す（バックアップ用）。"""
    tables = fetch_df(
        conn,
        """
        SELECT name
          FROM sqlite_master
         WHERE type='table'
           AND name NOT LIKE 'sqlite_%'
         ORDER BY name
        """,
    )
    bio = BytesIO()
    with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for _, row in tables.iterrows():
            t = str(row["name"])
            df = fetch_df(conn, f"SELECT * FROM {t};")
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            zf.writestr(f"{t}.csv", csv_bytes)
    return bio.getvalue()


def list_records_between(conn, resident_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    """start_date〜end_date（両端含む）のレコードを取得（削除除外）。"""
    return fetch_df(
        conn,
        """
        SELECT r.*,
               (SELECT COUNT(1) FROM daily_patrols p WHERE p.record_id=r.id) AS patrol_count
          FROM daily_records r
         WHERE r.resident_id=?
           AND r.record_date BETWEEN ? AND ?
           AND r.is_deleted=0
         ORDER BY r.record_date ASC,
                  (r.record_time_hh IS NULL) ASC,
                  r.record_time_hh ASC,
                  r.record_time_mm ASC,
                  r.id ASC
        """,
        (resident_id, start_date, end_date),
    )


def build_week_timeline(conn, resident_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    """1週間分を“項目ごと”にばらして時系列で返す（印刷/提出用）。"""
    recs = list_records_between(conn, resident_id, start_date, end_date)
    if recs.empty:
        return pd.DataFrame(columns=["日付", "時刻", "項目", "内容", "勤務", "記録者"])

    rows = []
    for _, r in recs.iterrows():
        rid = int(r["id"])
        d = str(r.get("record_date") or "")
        t = fmt_time(r.get("record_time_hh"), r.get("record_time_mm"))
        shift = str(r.get("shift") or "")
        who = str(r.get("recorder_name") or "")

        def add(item, content):
            content = (content or "").strip()
            if content == "":
                return
            rows.append({"日付": d, "時刻": t, "項目": item, "内容": content, "勤務": shift, "記録者": who})

        # ① 支援記録
        sc = scene_display(r.get("scene"))
        sn = (r.get("scene_note") or "").strip()
        add("①支援記録", f"{sc}：{sn}" if sn else f"{sc}")

        # ② バイタル（朝/夕）
        def vit_line(prefix, temp, sys, dia, pulse, spo2):
            parts = []
            if temp is not None:
                parts.append(f"体温 {float(temp):.1f}℃")
            if sys is not None or dia is not None:
                parts.append(f"血圧 {sys if sys is not None else '--'}/{dia if dia is not None else '--'}")
            if pulse is not None:
                parts.append(f"脈拍 {int(pulse)}")
            if spo2 is not None:
                parts.append(f"SpO₂ {int(spo2)}%")
            return (prefix + " " + " / ".join(parts)).strip() if parts else ""

        am = vit_line(
            "朝",
            safe_float(r.get("temp_am")),
            safe_int(r.get("bp_sys_am")),
            safe_int(r.get("bp_dia_am")),
            safe_int(r.get("pulse_am")),
            safe_int(r.get("spo2_am")),
        )
        pm = vit_line(
            "夕",
            safe_float(r.get("temp_pm")),
            safe_int(r.get("bp_sys_pm")),
            safe_int(r.get("bp_dia_pm")),
            safe_int(r.get("pulse_pm")),
            safe_int(r.get("spo2_pm")),
        )
        if am:
            add("②バイタル", am)
        if pm:
            add("②バイタル", pm)

        # ③ 食事
        meals = []
        if int(r.get("meal_bf_done") or 0) == 1:
            meals.append(f"朝 {int(r.get('meal_bf_score') or 0)}/10")
        if int(r.get("meal_lu_done") or 0) == 1:
            meals.append(f"昼 {int(r.get('meal_lu_score') or 0)}/10")
        if int(r.get("meal_di_done") or 0) == 1:
            meals.append(f"夕 {int(r.get('meal_di_score') or 0)}/10")
        if meals:
            add("③食事", " / ".join(meals))

        # ④ 服薬
        meds = []
        if int(r.get("med_morning") or 0) == 1:
            meds.append("朝")
        if int(r.get("med_noon") or 0) == 1:
            meds.append("昼")
        if int(r.get("med_evening") or 0) == 1:
            meds.append("夕")
        if int(r.get("med_bed") or 0) == 1:
            meds.append("寝る前")
        if meds:
            add("④服薬", " / ".join(meds))

        # ⑥ 特記事項
        note = (r.get("note") or "").strip()
        if note:
            add("⑥特記事項", note)

        # ⑤ 巡視（巡視時刻優先）
        if int(r.get("patrol_count") or 0) > 0:
            pat = load_patrols(conn, rid)
            for _, p in pat.iterrows():
                pt = fmt_time(p.get("patrol_time_hh"), p.get("patrol_time_mm"))
                status = (p.get("status") or "").strip()
                memo = (p.get("memo") or "").strip()
                intervened = "対応あり" if int(p.get("intervened") or 0) == 1 else ""
                door = "ドア開放" if int(p.get("door_opened") or 0) == 1 else ""
                safety = (p.get("safety_checks") or "").strip()
                bits = [b for b in [status, safety, intervened, door] if b]
                head = f"巡視{int(p.get('patrol_no') or 0)} {pt}"
                if bits:
                    head += "（" + " / ".join(bits) + "）"
                line = head + (f" / メモ：{memo}" if memo else "")
                rows.append(
                    {"日付": d, "時刻": pt if pt != "--:--" else t, "項目": "⑤巡視", "内容": line, "勤務": shift, "記録者": who}
                )

    df = pd.DataFrame(rows)

    def sort_key(row):
        d = row["日付"]
        tt = row["時刻"]
        try:
            tt2 = "99:99" if tt == "--:--" else tt
            return d + " " + tt2
        except Exception:
            return d + " 99:99"

    df["_k"] = df.apply(sort_key, axis=1)
    df = df.sort_values("_k", ascending=True).drop(columns=["_k"]).reset_index(drop=True)
    return df


# -------------------------
# Handover (申し送り)
# -------------------------
def add_handover_from_note(
    conn, *, unit_id: int, resident_id: int | None, handover_date: str, content: str, created_by: str, source_record_id: int | None
):
    content = (content or "").strip()
    if content == "":
        return None
    now = now_iso()
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


def list_likes(conn, handover_id: int):
    return fetch_df(
        conn,
        """
        SELECT user_name, created_at
          FROM handover_reactions
         WHERE handover_id=? AND reaction_type='like'
         ORDER BY created_at ASC, id ASC
        """,
        (handover_id,),
    )


def has_like(conn, *, handover_id: int, user_name: str) -> bool:
    df = fetch_df(
        conn,
        "SELECT 1 FROM handover_reactions WHERE handover_id=? AND user_name=? AND reaction_type='like' LIMIT 1",
        (handover_id, user_name),
    )
    return not df.empty


def toggle_like(conn, *, handover_id: int, user_name: str):
    now = now_iso()
    if has_like(conn, handover_id=handover_id, user_name=user_name):
        exec_sql(conn, "DELETE FROM handover_reactions WHERE handover_id=? AND user_name=? AND reaction_type='like'", (handover_id, user_name))
    else:
        exec_sql(
            conn,
            "INSERT OR IGNORE INTO handover_reactions(handover_id, user_name, reaction_type, created_at) VALUES(?,?, 'like', ?)",
            (handover_id, user_name, now),
        )


# -------------------------
# Reset strategy (epoch)
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
# CSS (Mobile First)
# -------------------------
def inject_css(is_alert: bool):
    danger = "#e11d48"  # vivid red
    accent = "#2563eb"
    btn = danger if is_alert else accent
    title = danger if is_alert else "#0f172a"
    st.markdown(
        f"""
<style>
:root {{
  --danger: {danger};
  --accent: {accent};
  --btn: {btn};
  --title: {title};
  --card:#ffffff;
  --bg:#f4f6f9;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,0.12);
}}

.stApp {{ background: var(--bg); color: var(--text); }}
.block-container {{ padding-top: .8rem; padding-bottom: 2.2rem; max-width: 1100px; }}

/* Title: never clipped */
.app-title {{
  font-size: 20px;
  font-weight: 900;
  line-height: 1.2;
  color: var(--title);
  margin: 0 0 .25rem 0;
  word-break: break-word;
}}
.app-sub {{
  font-size: 12px;
  color: var(--muted);
  margin-bottom: .6rem;
}}

/* Card */
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px 14px;
  margin: 10px 0 12px 0;
}}
.h {{
  font-size: 16px;
  font-weight: 900;
  margin: 0 0 8px 0;
}}
.h.danger {{
  color: var(--danger);
  font-weight: 1000;
}}
.p {{
  font-size: 13px;
  color: var(--muted);
  margin: 0 0 10px 0;
}}

/* Inputs / labels bigger for mobile */
label, .stMarkdown, .stTextInput, .stSelectbox, .stTextArea, .stNumberInput, .stToggle, .stCheckbox {{
  font-size: 16px !important;
}}
textarea {{ border-radius: 14px !important; }}

/* Buttons: large & easy tap */
.stButton > button {{
  width: 100%;
  border-radius: 14px !important;
  padding: 0.9rem 1rem !important;
  font-size: 16px !important;
  font-weight: 1000 !important;
  background: var(--btn) !important;
  color: white !important;
  border: 1px solid rgba(0,0,0,0.06) !important;
}}
.stButton > button:hover {{
  filter: brightness(0.98);
  transform: translateY(-1px);
  transition: 120ms ease;
}}

.meta {{
  font-size: 12px;
  color: rgba(15,23,42,0.72);
}}

.badge {{
  display:inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(37,99,235,0.08);
  font-size: 12px;
  font-weight: 900;
}}
.note-alert {{
  color: var(--danger);
  font-weight: 1000;
}}
</style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------
# main
# -------------------------
def main():
    st.set_page_config(page_title="介護記録", layout="centered")

    ensure_epoch()
    conn = get_conn()
    init_db(conn)

    # Sidebar: minimum
    st.sidebar.title("📌 条件")
    units_df = fetch_df(conn, "SELECT id, name FROM units WHERE is_active=1 ORDER BY id;")
    unit_name = st.sidebar.selectbox("ユニット", units_df["name"].tolist(), index=0)
    unit_id = int(units_df.loc[units_df["name"] == unit_name, "id"].iloc[0])

    target_date = st.sidebar.date_input("日付", value=datetime.now(JST).date())
    target_date_str = target_date.isoformat()

    shift = st.sidebar.radio("勤務区分", ["日勤", "夜勤"], index=0)

    st.sidebar.divider()
    recorder_name = st.sidebar.text_input("記録者名（必須）", value=st.session_state.get("recorder_name", ""))
    st.session_state["recorder_name"] = recorder_name

    # Backup (全データCSV)
    with st.sidebar.expander("🧯 全データのバックアップ（CSV）", expanded=False):
        st.caption("万が一に備えて、全テーブルをzipで保存できます。")
        if st.button("📦 バックアップZIPを作成", use_container_width=True, key="mk_backup_zip"):
            zbytes = export_all_tables_zip(conn)
            st.session_state["__backup_zip__"] = zbytes

        zbytes = st.session_state.get("__backup_zip__")
        if zbytes:
            st.download_button(
                "⬇️ ダウンロード（CSV.zip）",
                data=zbytes,
                file_name=f"kaigo_backup_{datetime.now(JST).strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True,
            )

    residents_df = fetch_df(
        conn,
        "SELECT id, name, kubun, disease FROM residents WHERE unit_id=? AND is_active=1 ORDER BY name;",
        (unit_id,),
    )
    if residents_df.empty:
        st.error("このユニットに利用者がいません。")
        conn.close()
        return

    r_opts = residents_df.to_dict(orient="records")

    def _r_label_sidebar(row):
        k = (str(row.get("kubun") or "")).strip() or "-"
        d = (str(row.get("disease") or "")).strip() or "-"
        return f"{row['name']}（区分:{k} / 病名:{d}）"

    sel_rr = st.sidebar.selectbox("利用者", options=r_opts, index=0, format_func=_r_label_sidebar)
    resident_id = int(sel_rr["id"])
    sel_name = str(sel_rr["name"])

    sel_row = residents_df.loc[residents_df["id"] == resident_id].iloc[0]
    kubun = (str(sel_row.get("kubun") or "")).strip() or "-"
    disease = (str(sel_row.get("disease") or "")).strip() or "-"
    resident_meta = f"区分：{kubun} / 病名：{disease}"

    # 利用者マスタ（区分・症名）編集
    with st.sidebar.expander("👤 利用者情報（区分・症名）", expanded=False):
        k_key = f"edit_kubun_{resident_id}"
        d_key = f"edit_disease_{resident_id}"
        kubun_in = st.text_input("区分（障害支援区分）", value=(str(sel_row.get("kubun") or "")).strip(), key=k_key)
        disease_in = st.text_input("症名（診断名）", value=(str(sel_row.get("disease") or "")).strip(), key=d_key)
        if st.button("💾 利用者情報を保存", use_container_width=True, key=f"save_resident_{resident_id}"):
            update_resident_master(conn, resident_id=resident_id, kubun=kubun_in, disease=disease_in)
            st.success("✅ 利用者情報を保存しました")
            st.rerun()

    # ----- alert state (⑥の入力中判定) -----
    note_preview = (st.session_state.get(add_key("note"), "") or "").strip()
    special_flag_preview = bool(st.session_state.get(add_key("special_flag"), False))
    is_alert = special_flag_preview or (len(note_preview) > 0)

    inject_css(is_alert)

    st.markdown(f'<div class="app-title">🧾 介護記録</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="app-sub">{unit_name} / {target_date_str} / {sel_name}（{resident_meta}）</div>', unsafe_allow_html=True)
    show_toast_if_needed()

    tab_in, tab_list, tab_ho, tab_print = st.tabs(["✍️ 入力", "📋 経過一覧", "🗒️ 申し送り", "🖨️ 印刷用出力（週報）"])

    # -------------------------
    # 入力
    # -------------------------
    with tab_in:
        # Save button top
        save_top = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("save_top"))

        # --- 主時刻（自動）: 巡視があれば最新、なければ現在時刻（5分丸め）
        hh_options = ["未選択"] + list(range(0, 24))
        mm_options = ["未選択"] + list(range(0, 60, 5))

        def _patrol_time(hh, mm):
            if hh == "未選択" or mm == "未選択":
                return None
            try:
                return (int(hh), int(mm))
            except Exception:
                return None

        # session_state から巡視の入力を先読み（順番が①→⑤でもOK）
        p1 = _patrol_time(st.session_state.get(add_key("p1_hh"), "未選択"), st.session_state.get(add_key("p1_mm"), "未選択"))
        p2 = _patrol_time(st.session_state.get(add_key("p2_hh"), "未選択"), st.session_state.get(add_key("p2_mm"), "未選択"))
        patrol_times = [t for t in [p1, p2] if t]
        patrol_main = max(patrol_times) if patrol_times else None

        default_dt = round_now_5min()
        auto_hh, auto_mm = (patrol_main if patrol_main else (default_dt.hour, default_dt.minute))
        auto_time_label = fmt_time(auto_hh, auto_mm) + ("（巡視から自動）" if patrol_main else "（現在時刻 自動）")

        # Optional manual override (normally off)
        manual_time = st.toggle("時刻を手動で変更する（通常は不要）", value=False, key=add_key("manual_time"))
        if manual_time:
            t = st.time_input("主時刻（手動）", value=dtime(hour=int(auto_hh), minute=int(auto_mm)), key=add_key("manual_time_val"))
            main_hh, main_mm = int(t.hour), int(t.minute)
            time_label = fmt_time(main_hh, main_mm) + "（手動）"
        else:
            main_hh, main_mm = int(auto_hh), int(auto_mm)
            time_label = auto_time_label

        # ① 支援記録
        st.markdown('<div class="card">', unsafe_allow_html=True)
        hcls = "h danger" if is_alert else "h"
        st.markdown(f'<div class="{hcls}">① 支援記録</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="p">時刻は自動採用します： <span class="badge">{time_label}</span></div>', unsafe_allow_html=True)

        scene = st.selectbox("場面", SCENES, index=2, format_func=scene_display, key=add_key("scene"))
        if str(scene) != "":
            scene_note = st.text_input("記録内容（フリーワード）", value="", key=add_key("scene_note"),
                                       placeholder="例：表情良好／声かけで落ち着く／水分摂取 等")
        else:
            scene_note = ""
            st.caption("※ 場面を選択すると、フリーワード入力欄が表示されます。")
        st.markdown("</div>", unsafe_allow_html=True)

        # ② バイタル
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h">② バイタル（朝・夕）</div>', unsafe_allow_html=True)
        st.markdown('<div class="p">※デフォルトは未入力。入力して保存した項目のみ記録されます（空欄は保存しません）。</div>', unsafe_allow_html=True)

        latest = latest_vitals_anyday(conn, resident_id)

        def ph_float(key, fmt="%.1f"):
            v = safe_float(latest.get(key))
            if v is None:
                return ""
            try:
                return ("前回: " + (fmt % float(v)))
            except Exception:
                return f"前回: {v}"

        def ph_int(key):
            v = safe_int(latest.get(key))
            return f"前回: {v}" if v is not None else ""

        st.markdown("**朝**")
        am_rec = st.toggle("朝バイタルを記録する", value=False, key=add_key("am_rec"))
        am_temp_s = st.text_input("体温（℃）", value="", placeholder=ph_float("temp_am"), disabled=(not am_rec), key=add_key("am_temp_s"))
        am_sys_s  = st.text_input("血圧 上", value="", placeholder=ph_int("bp_sys_am"), disabled=(not am_rec), key=add_key("am_sys_s"))
        am_dia_s  = st.text_input("血圧 下", value="", placeholder=ph_int("bp_dia_am"), disabled=(not am_rec), key=add_key("am_dia_s"))
        am_pulse_s = st.text_input("脈拍", value="", placeholder=ph_int("pulse_am"), disabled=(not am_rec), key=add_key("am_pulse_s"))
        am_spo2_s  = st.text_input("SpO₂", value="", placeholder=ph_int("spo2_am"), disabled=(not am_rec), key=add_key("am_spo2_s"))

        st.markdown("**夕**")
        pm_rec = st.toggle("夕バイタルを記録する", value=False, key=add_key("pm_rec"))
        pm_temp_s = st.text_input("体温（℃） ", value="", placeholder=ph_float("temp_pm"), disabled=(not pm_rec), key=add_key("pm_temp_s"))
        pm_sys_s  = st.text_input("血圧 上 ", value="", placeholder=ph_int("bp_sys_pm"), disabled=(not pm_rec), key=add_key("pm_sys_s"))
        pm_dia_s  = st.text_input("血圧 下 ", value="", placeholder=ph_int("bp_dia_pm"), disabled=(not pm_rec), key=add_key("pm_dia_s"))
        pm_pulse_s = st.text_input("脈拍 ", value="", placeholder=ph_int("pulse_pm"), disabled=(not pm_rec), key=add_key("pm_pulse_s"))
        pm_spo2_s  = st.text_input("SpO₂ ", value="", placeholder=ph_int("spo2_pm"), disabled=(not pm_rec), key=add_key("pm_spo2_s"))

        st.markdown("</div>", unsafe_allow_html=True)

        # ③ 食事
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h">③ 食事</div>', unsafe_allow_html=True)
        bf_done = st.toggle("朝食あり", value=False, key=add_key("bf_done"))
        bf_score = st.slider("朝食量（1〜10）", 1, 10, value=5, key=add_key("bf_score"), disabled=(not bf_done))
        lu_done = st.toggle("昼食あり", value=False, key=add_key("lu_done"))
        lu_score = st.slider("昼食量（1〜10）", 1, 10, value=5, key=add_key("lu_score"), disabled=(not lu_done))
        di_done = st.toggle("夕食あり", value=False, key=add_key("di_done"))
        di_score = st.slider("夕食量（1〜10）", 1, 10, value=5, key=add_key("di_score"), disabled=(not di_done))
        st.markdown("</div>", unsafe_allow_html=True)

        # ④ 服薬
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h">④ 服薬</div>', unsafe_allow_html=True)
        med_m = st.checkbox("朝", value=False, key=add_key("med_m"))
        med_n = st.checkbox("昼", value=False, key=add_key("med_n"))
        med_e = st.checkbox("夕", value=False, key=add_key("med_e"))
        med_b = st.checkbox("寝る前", value=False, key=add_key("med_b"))
        st.markdown("</div>", unsafe_allow_html=True)

        # ⑤ 巡視
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h">⑤ 巡視</div>', unsafe_allow_html=True)
        enable_patrol = st.checkbox("巡視を記録する", value=False, key=add_key("enable_patrol"))
        safety_options = ["室温OK", "体調変化なし", "危険物なし", "転倒リスクなし"]
        patrol_status_options = ["", "就寝中（静か）", "起きている（静か）", "起きている（落ち着かない）", "不穏", "不在"]

        patrol_list = []
        if enable_patrol:
            st.markdown("**巡視1**")
            p1_hh = st.selectbox("巡視1：時", hh_options, index=0, key=add_key("p1_hh"))
            p1_mm = st.selectbox("巡視1：分", mm_options, index=0, key=add_key("p1_mm"))
            p1_status = st.selectbox("巡視1：状況", patrol_status_options, index=0, key=add_key("p1_status"))
            p1_memo = st.text_input("巡視1：メモ", value="", key=add_key("p1_memo"))
            p1_int = st.checkbox("巡視1：対応した", value=False, key=add_key("p1_int"))
            p1_door = st.checkbox("巡視1：居室ドアを開けた", value=False, key=add_key("p1_door"))
            p1_safety = st.multiselect("巡視1：安全チェック", safety_options, default=[], key=add_key("p1_safety"))

            st.markdown("---")
            st.markdown("**巡視2**")
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

        st.markdown("</div>", unsafe_allow_html=True)

        # ⑥ 特記事項
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h">⑥ 特記事項</div>', unsafe_allow_html=True)
        special_flag = st.checkbox("⚠ 特記事項あり（申し送りにも共有する）", value=False, key=add_key("special_flag"))
        note = st.text_area("特記事項（自由記述）", value="", height=200, key=add_key("note"),
                            placeholder="例：普段と違う行動／不穏の兆候／転倒・ヒヤリハット／対応内容と結果 等")
        st.markdown("</div>", unsafe_allow_html=True)

        # Save button bottom
        save_bottom = st.button("💾 保存して記録を追加", use_container_width=True, key=add_key("save_bottom"))

        # ---- Save action
        if save_top or save_bottom:
            if recorder_name.strip() == "":
                st.error("記録者名（必須）を入力してください（サイドバー）。")
            else:
                # 主時刻確定：巡視があれば最新巡視（max）、なければ現在（5分丸め）
                patrol_times2 = []
                for p in patrol_list:
                    hh = p.get("patrol_time_hh")
                    mm = p.get("patrol_time_mm")
                    if hh is None or mm is None:
                        continue
                    patrol_times2.append((int(hh), int(mm)))
                main_from_patrol = max(patrol_times2) if patrol_times2 else None
                if (not manual_time) and main_from_patrol:
                    main_hh2, main_mm2 = main_from_patrol
                else:
                    main_hh2, main_mm2 = main_hh, main_mm

                # Vitals: default blank -> None（入力した項目だけ保存）
                am_temp_v = parse_float_str(am_temp_s) if bool(am_rec) else None
                am_sys_v = parse_int_str(am_sys_s) if bool(am_rec) else None
                am_dia_v = parse_int_str(am_dia_s) if bool(am_rec) else None
                am_pulse_v = parse_int_str(am_pulse_s) if bool(am_rec) else None
                am_spo2_v = parse_int_str(am_spo2_s) if bool(am_rec) else None

                pm_temp_v = parse_float_str(pm_temp_s) if bool(pm_rec) else None
                pm_sys_v = parse_int_str(pm_sys_s) if bool(pm_rec) else None
                pm_dia_v = parse_int_str(pm_dia_s) if bool(pm_rec) else None
                pm_pulse_v = parse_int_str(pm_pulse_s) if bool(pm_rec) else None
                pm_spo2_v = parse_int_str(pm_spo2_s) if bool(pm_rec) else None

                wakeup_flag = 1 if str(scene) == "起床" else 0

                payload = {
                    "unit_id": unit_id,
                    "resident_id": resident_id,
                    "record_date": target_date_str,
                    "record_time_hh": int(main_hh2),
                    "record_time_mm": int(main_mm2),
                    "shift": shift,
                    "recorder_name": recorder_name.strip(),
                    "scene": scene if scene in SCENES else "ご様子",
                    "scene_note": (scene_note or "").strip() if str(scene) != "" else "",
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

                    "note": (note or "").strip(),
                }

                try:
                    record_id = upsert_record(conn, payload, patrol_list)
                except sqlite3.OperationalError as e:
                    st.error(f"DBエラー: {e}")
                    st.stop()

                # 特記事項 → 申し送り（チェックONかつ内容あり）
                if bool(special_flag) and (payload["note"] or "").strip():
                    add_handover_from_note(
                        conn,
                        unit_id=unit_id,
                        resident_id=resident_id,
                        handover_date=target_date_str,
                        content=payload["note"],
                        created_by=recorder_name.strip(),
                        source_record_id=record_id,
                    )

                bump_epoch_and_rerun()

    # -------------------------
    # 経過一覧
    # -------------------------
    with tab_list:
        st.markdown("### 📋 支援経過記録（直近が上）")
        st.caption(f"利用者：{sel_name}（{resident_meta}）")

        recs = list_records_for_day(conn, resident_id, target_date_str)
        if recs.empty:
            st.info("この日の記録はまだありません。")
        else:
            for _, r in recs.iterrows():
                rid = int(r["id"])
                t = fmt_time(r.get("record_time_hh"), r.get("record_time_mm"))
                scene = scene_display(r.get("scene"))
                created_at = fmt_dt(r.get("created_at"))
                updated_at = fmt_dt(r.get("updated_at"))
                patrol_count = int(r.get("patrol_count", 0) or 0)

                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"**{t}** 　<span class='badge'>{scene}</span> 　記録者：{r.get('recorder_name')}", unsafe_allow_html=True)
                st.markdown(f"<div class='meta'>作成:{created_at} / 更新:{updated_at} / 巡視:{patrol_count}回</div>", unsafe_allow_html=True)

                # --- ① 支援記録（場面メモ） ---
                sn = (r.get("scene_note") or "").strip()
                if sn:
                    st.markdown(f"- 【場面メモ】{sn}")
                else:
                    st.caption("【場面メモ】なし")

                # --- ② バイタル（朝・夕） ---
                def _v(v, fmt=None):
                    if v is None:
                        return None
                    try:
                        if pd.isna(v):
                            return None
                    except Exception:
                        pass
                    return fmt(v) if fmt else v

                am = {
                    "体温": _v(safe_float(r.get("temp_am")), lambda x: f"{x:.1f}℃"),
                    "血圧": None,
                    "脈拍": _v(safe_int(r.get("pulse_am")), lambda x: f"{x}"),
                    "SpO2": _v(safe_int(r.get("spo2_am")), lambda x: f"{x}%"),
                }
                sys_am = safe_int(r.get("bp_sys_am"))
                dia_am = safe_int(r.get("bp_dia_am"))
                if sys_am is not None or dia_am is not None:
                    am["血圧"] = f"{sys_am if sys_am is not None else '--'}/{dia_am if dia_am is not None else '--'}"

                pm = {
                    "体温": _v(safe_float(r.get("temp_pm")), lambda x: f"{x:.1f}℃"),
                    "血圧": None,
                    "脈拍": _v(safe_int(r.get("pulse_pm")), lambda x: f"{x}"),
                    "SpO2": _v(safe_int(r.get("spo2_pm")), lambda x: f"{x}%"),
                }
                sys_pm = safe_int(r.get("bp_sys_pm"))
                dia_pm = safe_int(r.get("bp_dia_pm"))
                if sys_pm is not None or dia_pm is not None:
                    pm["血圧"] = f"{sys_pm if sys_pm is not None else '--'}/{dia_pm if dia_pm is not None else '--'}"

                def _vline(label, d):
                    parts = [f"{k}:{v}" for k, v in d.items() if v not in (None, "", "--/--")]
                    return f"【{label}】" + " / ".join(parts) if parts else f"【{label}】記録なし"

                st.markdown(f"- {_vline('バイタル（朝）', am)}")
                st.markdown(f"- {_vline('バイタル（夕）', pm)}")

                # --- ③ 食事 ---
                bf_done0 = int(r.get("meal_bf_done") or 0)
                lu_done0 = int(r.get("meal_lu_done") or 0)
                di_done0 = int(r.get("meal_di_done") or 0)
                meal_parts = []
                meal_parts.append(f"朝:{int(r.get('meal_bf_score') or 0)}" if bf_done0 else "朝:-")
                meal_parts.append(f"昼:{int(r.get('meal_lu_score') or 0)}" if lu_done0 else "昼:-")
                meal_parts.append(f"夕:{int(r.get('meal_di_score') or 0)}" if di_done0 else "夕:-")
                if bf_done0 or lu_done0 or di_done0:
                    st.markdown("- 【食事】" + " / ".join(meal_parts))
                else:
                    st.caption("【食事】記録なし")

                # --- ④ 服薬 ---
                meds = []
                if int(r.get("med_morning") or 0) == 1: meds.append("朝")
                if int(r.get("med_noon") or 0) == 1: meds.append("昼")
                if int(r.get("med_evening") or 0) == 1: meds.append("夕")
                if int(r.get("med_bed") or 0) == 1: meds.append("寝る前")
                if meds:
                    st.markdown("- 【服薬】" + " / ".join(meds))
                else:
                    st.caption("【服薬】記録なし")

                # --- ⑤ 巡視 ---
                if patrol_count > 0:
                    pat = load_patrols(conn, rid)
                    st.markdown("**【巡視】**")
                    for _, p in pat.iterrows():
                        pt = fmt_time(p.get("patrol_time_hh"), p.get("patrol_time_mm"))
                        status = (p.get("status") or "").strip()
                        memo = (p.get("memo") or "").strip()
                        intervened = "対応あり" if int(p.get("intervened") or 0) == 1 else ""
                        door = "ドア開放" if int(p.get("door_opened") or 0) == 1 else ""
                        safety = (p.get("safety_checks") or "").strip()
                        bits = [b for b in [status, safety, intervened, door] if b]
                        head = f"- 巡視{int(p.get('patrol_no') or 0)} {pt}"
                        if bits:
                            head += "（" + " / ".join(bits) + "）"
                        st.markdown(head)
                        if memo:
                            st.markdown(f"  - メモ：{memo}")
                else:
                    st.caption("【巡視】記録なし")

                # --- ⑥ 特記事項（赤） ---
                note_head = (r.get("note_head") or "").strip()
                if note_head:
                    st.markdown(f"<div class='note-alert'>【特記事項】{note_head}</div>", unsafe_allow_html=True)
                else:
                    st.caption("【特記事項】なし")

                if st.button("削除（論理削除）", key=f"del_{rid}"):
                    soft_delete_record(conn, rid)
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------
    # 申し送り
    # -------------------------
    with tab_ho:
        st.markdown("### 🗒️ 申し送り（連絡帳）")
        st.caption("⑥特記事項（チェックONで保存）→ここに自動反映。リアクションは 👍 のみ。")

        # 新規申し送り（自由記述）
        st.markdown("#### ➕ 新規申し送り作成")
        st.caption("特記事項以外の連絡も、ここから直接投稿できます。")
        ho_scope = st.radio("対象", ["この利用者", "全体（ユニット）"], horizontal=True, index=0,
                            key=f"ho_scope_{unit_id}_{resident_id}_{target_date_str}")
        ho_text = st.text_area(
            "申し送り内容（自由記述）",
            value="",
            height=140,
            placeholder="例：明日は通院予定／家族から電話あり／買い物依頼 など",
            key=f"ho_text_{unit_id}_{resident_id}_{target_date_str}",
        )
        if st.button("📮 申し送りを投稿", use_container_width=True, key=f"post_ho_{unit_id}_{resident_id}_{target_date_str}"):
            if recorder_name.strip() == "":
                st.error("投稿するには、サイドバーの『記録者名（必須）』を入力してください。")
            else:
                content = (ho_text or "").strip()
                if content == "":
                    st.error("申し送り内容を入力してください。")
                else:
                    add_handover_from_note(
                        conn,
                        unit_id=unit_id,
                        resident_id=(resident_id if ho_scope == "この利用者" else None),
                        handover_date=target_date_str,
                        content=content,
                        created_by=recorder_name.strip(),
                        source_record_id=None,
                    )
                    st.success("✅ 申し送りを投稿しました")
                    st.rerun()

        st.divider()

        ho = list_handovers(conn, unit_id=unit_id, handover_date=target_date_str)
        res_map = {int(r["id"]): str(r["name"]) for _, r in residents_df.iterrows()}

        if ho.empty:
            st.info("この日の申し送りはまだありません。")
        else:
            for _, h in ho.iterrows():
                hid = int(h["id"])
                rid = safe_int(h.get("resident_id"))
                rname = res_map.get(int(rid), "（全体）") if rid is not None else "（全体）"
                who = str(h.get("created_by") or "")
                content = str(h.get("content") or "").strip()
                created_at = fmt_dt(h.get("created_at"))

                likes = list_likes(conn, hid)
                like_names = [str(x) for x in likes["user_name"].tolist()] if not likes.empty else []
                like_count = len(like_names)
                names_txt = "、".join(like_names[:8]) + ("…" if len(like_names) > 8 else "")
                like_line = f"👍 {like_count}" + (f"（{names_txt}）" if like_count > 0 else "")

                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"**{rname}**  \n{content}")
                st.markdown(f"<div class='meta'>投稿：{created_at} / 投稿者：{who}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='meta' style='font-weight:900;'>{like_line}</div>", unsafe_allow_html=True)

                if recorder_name.strip() == "":
                    st.warning("👍 を押すには、サイドバーの『記録者名』を入力してください。")
                else:
                    liked = has_like(conn, handover_id=hid, user_name=recorder_name.strip())
                    btn_txt = "👍 いいね" if not liked else "👍 取り消し"
                    if st.button(btn_txt, key=f"like_{hid}"):
                        toggle_like(conn, handover_id=hid, user_name=recorder_name.strip())
                        st.rerun()

                if like_count > 0:
                    with st.expander("👍 履歴（誰がいつ）", expanded=False):
                        for _, lr in likes.iterrows():
                            st.markdown(f"- {lr['user_name']}（{fmt_dt(lr['created_at'])}）")

                st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------
    # 印刷用出力（週報）
    # -------------------------
    with tab_print:
        st.markdown("### 🖨️ 印刷用出力（週報）")
        st.caption("PCでの印刷・行政提出を想定した表示です。入力のしやすさ（スマホ）は維持します。")

        def _r_label(row):
            k = (str(row.get("kubun") or "")).strip() or "-"
            d = (str(row.get("disease") or "")).strip() or "-"
            return f"{row['name']}（区分:{k} / 病名:{d}）"

        r_opts2 = residents_df.to_dict(orient="records")
        cur_idx = 0
        for i, rr in enumerate(r_opts2):
            if int(rr["id"]) == int(resident_id):
                cur_idx = i
                break

        sel_rr2 = st.selectbox("利用者（週報対象）", options=r_opts2, index=cur_idx, format_func=_r_label, key="print_resident")
        pr_resident_id = int(sel_rr2["id"])
        pr_name = str(sel_rr2["name"])
        pr_kubun = (str(sel_rr2.get("kubun") or "")).strip() or "-"
        pr_disease = (str(sel_rr2.get("disease") or "")).strip() or "-"

        start_dt = st.date_input("開始日（ここから7日間）", value=target_date, key="print_start")
        end_dt = start_dt + timedelta(days=6)
        start_s = start_dt.isoformat()
        end_s = end_dt.isoformat()

        st.markdown(f"**ユニット：{unit_name} / 利用者：{pr_name}（区分:{pr_kubun} / 病名:{pr_disease}）**")
        st.markdown(f"期間：{start_s} 〜 {end_s}（7日間）")

        df_week = build_week_timeline(conn, pr_resident_id, start_s, end_s)
        if df_week.empty:
            st.info("この期間の記録はありません。")
        else:
            st.dataframe(df_week, use_container_width=True, height=520)

            csv_bytes = df_week.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ CSVダウンロード",
                data=csv_bytes,
                file_name=f"weekly_{unit_name}_{pr_name}_{start_s}_to_{end_s}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            xbio = BytesIO()
            with pd.ExcelWriter(xbio, engine="openpyxl") as writer:
                df_week.to_excel(writer, index=False, sheet_name="週報")
            st.download_button(
                "⬇️ Excelダウンロード",
                data=xbio.getvalue(),
                file_name=f"weekly_{unit_name}_{pr_name}_{start_s}_to_{end_s}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            st.markdown("#### 印刷（PC）")
            st.caption("ブラウザの印刷機能（Ctrl+P / ⌘P）で印刷してください。表は提出向けに時系列で並びます。")

    conn.close()


if __name__ == "__main__":
    main()
