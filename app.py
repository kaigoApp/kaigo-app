# main.py  (Flet 0.80.5 対応 / 完成版 + 記録者保持 + 自動転記 + AI報告案 + urgentワンオペ)
# 実行:
#   py -m pip install flet==0.80.5
#   py -m flet run main.py

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import flet as ft


# =========================
# Theme / Constants
# =========================
APP_WIDTH = 400

HEADER = "#3CB7B5"  # Tiffany Blue
BG = "#FFF9F0"
CARD_BG = "white"
TEXT_DARK = "#1F2937"
MUTED = "#6B7280"
BORDER = ft.Colors.BLACK12
SHADOW = ft.BoxShadow(blur_radius=18, color=ft.Colors.BLACK12, offset=ft.Offset(0, 6))

DB_PATH = "care_app.db"

SLOTS = ["朝", "夕", "その他"]
STAFFS = ["管理者", "サビ管"] + [f"職員{i:02d}" for i in range(1, 16)]
RESIDENTS = [{"id": i, "code": chr(ord("A") + i), "name": f"利用者 {chr(ord('A') + i)}"} for i in range(20)]

MEAL_SLOTS = ["朝", "昼", "夕"]
MED_SLOTS = ["朝", "昼", "夕", "寝前"]
PATROL_ROUNDS = ["1回目", "2回目"]
PATROL_STATES = ["就寝", "覚醒", "不穏", "不眠"]

# condition 拡充（要件）
CONDITIONS = ["傾眠", "興奮", "不穏", "疼痛疑い", "いつも通り", "活気なし"]


# =========================
# DB
# =========================
def get_conn():
    return sqlite3.connect(DB_PATH)


def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols


def _safe_add_column(con: sqlite3.Connection, table: str, col: str, ddl: str):
    """
    ddl 例: "staff_name TEXT NOT NULL DEFAULT ''"
    """
    if not _has_column(con, table, col):
        cur = con.cursor()
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")
        con.commit()


def init_db_if_needed():
    """
    既存DBを生かす（DROPしない）。
    無ければ作成、あれば不足カラムだけMigration。
    """
    con = get_conn()
    cur = con.cursor()

    # residents
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS residents (
            id INTEGER PRIMARY KEY,
            code TEXT,
            name TEXT,
            diagnosis_main TEXT,
            diagnosis_free TEXT,
            care_level TEXT
        );
        """
    )

    # vitals
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vitals (
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            slot TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            temperature REAL NOT NULL,
            bp_high INTEGER NOT NULL,
            bp_low INTEGER NOT NULL,
            pulse INTEGER NOT NULL,
            spo2 INTEGER NOT NULL,
            respiration INTEGER NOT NULL,
            condition TEXT NOT NULL,
            staff_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (resident_id, ymd, slot)
        );
        """
    )

    # support_logs
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            slot TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            text TEXT NOT NULL,
            ai_sentiment TEXT NOT NULL DEFAULT 'neutral',
            staff_name TEXT NOT NULL DEFAULT ''
        );
        """
    )

    # handover_notes
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS handover_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ymd TEXT NOT NULL,
            slot TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            text TEXT NOT NULL,
            level TEXT NOT NULL,
            likes INTEGER NOT NULL DEFAULT 0,
            staff_name TEXT NOT NULL DEFAULT ''
        );
        """
    )

    # staff_sessions
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        """
    )

    # baths
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS baths (
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            status TEXT NOT NULL,
            staff_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (resident_id, ymd)
        );
        """
    )

    # meals
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meals (
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            slot TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            amount INTEGER NOT NULL,
            staff_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (resident_id, ymd, slot)
        );
        """
    )

    # meds
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meds (
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            slot TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            taken INTEGER NOT NULL,
            staff_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (resident_id, ymd, slot)
        );
        """
    )

    # patrols
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS patrols (
            resident_id INTEGER NOT NULL,
            ymd TEXT NOT NULL,
            round TEXT NOT NULL,
            hm TEXT NOT NULL,
            ts TEXT NOT NULL,
            state TEXT NOT NULL,
            safety_ok INTEGER NOT NULL,
            staff_name TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (resident_id, ymd, round)
        );
        """
    )

    # 既存DBへのMigration（不足列を追加）
    _safe_add_column(con, "support_logs", "ai_sentiment", "ai_sentiment TEXT NOT NULL DEFAULT 'neutral'")
    _safe_add_column(con, "support_logs", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "handover_notes", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "vitals", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "baths", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "meals", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "meds", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")
    _safe_add_column(con, "patrols", "staff_name", "staff_name TEXT NOT NULL DEFAULT ''")

    # residents 初期投入（不足分だけ埋める）
    cur.execute("SELECT COUNT(*) FROM residents;")
    cnt = int(cur.fetchone()[0] or 0)
    if cnt < len(RESIDENTS):
        cur.executemany(
            "INSERT OR REPLACE INTO residents (id, code, name, diagnosis_main, diagnosis_free, care_level) VALUES (?, ?, ?, ?, ?, ?);",
            [(r["id"], r["code"], r["name"], "", "", "") for r in RESIDENTS],
        )

    con.commit()
    con.close()


def upsert_vitals(data: dict):
    con = get_conn()
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO vitals (
            resident_id, ymd, slot, hm, ts,
            temperature, bp_high, bp_low, pulse, spo2, respiration, condition, staff_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            data["resident_id"],
            data["ymd"],
            data["slot"],
            data["hm"],
            data["ts"],
            data["temperature"],
            data["bp_high"],
            data["bp_low"],
            data["pulse"],
            data["spo2"],
            data["respiration"],
            data["condition"],
            data.get("staff_name", "") or "",
        ),
    )
    con.commit()
    con.close()


def _guess_ai_sentiment(text: str) -> str:
    t = (text or "").lower()
    neg_keys = [
        "【特記事項】",
        "警告",
        "要観察",
        "急変",
        "不穏",
        "不眠",
        "転倒",
        "発熱",
        "spo2が低",
        "血圧が高",
        "血圧が低",
        "呼吸数が多",
        "活気なし",
        "傾眠",
        "興奮",
        "疼痛",
        "報告",
        "連絡",
    ]
    pos_keys = ["安定", "問題ありません", "通常通り", "落ち着いて", "良眠", "完食", "服薬済"]
    if any(k.lower() in t for k in neg_keys):
        return "negative"
    if any(k.lower() in t for k in pos_keys):
        return "positive"
    return "neutral"


def add_progress_log(
    resident_id: int,
    ymd: str,
    slot: str,
    hm: str,
    ts: str,
    text: str,
    *,
    staff_name: str = "",
    ai_sentiment: str | None = None,
):
    con = get_conn()
    try:
        if ai_sentiment is None:
            ai_sentiment = _guess_ai_sentiment(text)

        cur = con.cursor()
        if _has_column(con, "support_logs", "ai_sentiment") and _has_column(con, "support_logs", "staff_name"):
            cur.execute(
                """
                INSERT INTO support_logs (resident_id, ymd, slot, hm, ts, text, ai_sentiment, staff_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (resident_id, ymd, slot, hm, ts, text, ai_sentiment, staff_name or ""),
            )
        elif _has_column(con, "support_logs", "ai_sentiment"):
            cur.execute(
                """
                INSERT INTO support_logs (resident_id, ymd, slot, hm, ts, text, ai_sentiment)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (resident_id, ymd, slot, hm, ts, text, ai_sentiment),
            )
        else:
            cur.execute(
                """
                INSERT INTO support_logs (resident_id, ymd, slot, hm, ts, text)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (resident_id, ymd, slot, hm, ts, text),
            )
        con.commit()
    finally:
        con.close()


def add_handover_note(ymd: str, slot: str, hm: str, ts: str, text: str, *, level: str = "normal", staff_name: str = ""):
    con = get_conn()
    cur = con.cursor()

    if _has_column(con, "handover_notes", "staff_name"):
        cur.execute(
            """
            INSERT INTO handover_notes (ymd, slot, hm, ts, text, level, likes, staff_name)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?);
            """,
            (ymd, slot, hm, ts, text, level, staff_name or ""),
        )
    else:
        cur.execute(
            """
            INSERT INTO handover_notes (ymd, slot, hm, ts, text, level, likes)
            VALUES (?, ?, ?, ?, ?, ?, 0);
            """,
            (ymd, slot, hm, ts, text, level),
        )

    con.commit()
    con.close()


def inc_handover_like(note_id: int):
    con = get_conn()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE handover_notes
        SET likes = likes + 1
        WHERE id = ?;
        """,
        (note_id,),
    )
    con.commit()
    con.close()


def upsert_bath(resident_id: int, ymd: str, hm: str, ts: str, status: str, *, staff_name: str = ""):
    con = get_conn()
    cur = con.cursor()
    if _has_column(con, "baths", "staff_name"):
        cur.execute(
            """
            INSERT OR REPLACE INTO baths (resident_id, ymd, hm, ts, status, staff_name)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, hm, ts, status, staff_name or ""),
        )
    else:
        cur.execute(
            """
            INSERT OR REPLACE INTO baths (resident_id, ymd, hm, ts, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, hm, ts, status),
        )
    con.commit()
    con.close()


def upsert_meal(resident_id: int, ymd: str, slot: str, hm: str, ts: str, amount: int, *, staff_name: str = ""):
    con = get_conn()
    cur = con.cursor()
    if _has_column(con, "meals", "staff_name"):
        cur.execute(
            """
            INSERT OR REPLACE INTO meals (resident_id, ymd, slot, hm, ts, amount, staff_name)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, slot, hm, ts, int(amount), staff_name or ""),
        )
    else:
        cur.execute(
            """
            INSERT OR REPLACE INTO meals (resident_id, ymd, slot, hm, ts, amount)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, slot, hm, ts, int(amount)),
        )
    con.commit()
    con.close()


def upsert_meds(resident_id: int, ymd: str, slot: str, hm: str, ts: str, taken: int, *, staff_name: str = ""):
    con = get_conn()
    cur = con.cursor()
    if _has_column(con, "meds", "staff_name"):
        cur.execute(
            """
            INSERT OR REPLACE INTO meds (resident_id, ymd, slot, hm, ts, taken, staff_name)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, slot, hm, ts, int(taken), staff_name or ""),
        )
    else:
        cur.execute(
            """
            INSERT OR REPLACE INTO meds (resident_id, ymd, slot, hm, ts, taken)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, slot, hm, ts, int(taken)),
        )
    con.commit()
    con.close()


def upsert_patrol(resident_id: int, ymd: str, round_name: str, hm: str, ts: str, state: str, safety_ok: int, *, staff_name: str = ""):
    con = get_conn()
    cur = con.cursor()
    if _has_column(con, "patrols", "staff_name"):
        cur.execute(
            """
            INSERT OR REPLACE INTO patrols (resident_id, ymd, round, hm, ts, state, safety_ok, staff_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, round_name, hm, ts, state, int(safety_ok), staff_name or ""),
        )
    else:
        cur.execute(
            """
            INSERT OR REPLACE INTO patrols (resident_id, ymd, round, hm, ts, state, safety_ok)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (resident_id, ymd, round_name, hm, ts, state, int(safety_ok)),
        )
    con.commit()
    con.close()


def get_prev_vitals(resident_id: int, ymd: str, slot: str):
    con = get_conn()
    cur = con.cursor()

    y = (datetime.strptime(ymd, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    cur.execute(
        "SELECT temperature, bp_high, bp_low, pulse, spo2, respiration, condition FROM vitals WHERE resident_id=? AND ymd=? AND slot=?;",
        (resident_id, y, slot),
    )
    row = cur.fetchone()
    if row:
        con.close()
        return row

    cur.execute(
        """
        SELECT temperature, bp_high, bp_low, pulse, spo2, respiration, condition
        FROM vitals
        WHERE resident_id=?
        ORDER BY ts DESC
        LIMIT 1;
        """,
        (resident_id,),
    )
    row = cur.fetchone()
    con.close()
    return row


def get_vital_hm_map(ymd: str, slot: str) -> dict[int, str]:
    con = get_conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT resident_id, hm
        FROM vitals
        WHERE ymd=? AND slot=?;
        """,
        (ymd, slot),
    )
    rows = cur.fetchall()
    con.close()
    out: dict[int, str] = {}
    for rid, hm in rows:
        try:
            out[int(rid)] = str(hm)
        except Exception:
            pass
    return out


def get_bath_map(ymd: str) -> dict[int, tuple[str, str]]:
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT resident_id, status, hm FROM baths WHERE ymd=?;", (ymd,))
    rows = cur.fetchall()
    con.close()
    out: dict[int, tuple[str, str]] = {}
    for rid, status, hm in rows:
        out[int(rid)] = (str(status), str(hm))
    return out


def get_meal_map(ymd: str, slot: str) -> dict[int, tuple[int, str]]:
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT resident_id, amount, hm FROM meals WHERE ymd=? AND slot=?;", (ymd, slot))
    rows = cur.fetchall()
    con.close()
    out: dict[int, tuple[int, str]] = {}
    for rid, amt, hm in rows:
        out[int(rid)] = (int(amt), str(hm))
    return out


def get_meds_map(ymd: str, slot: str) -> dict[int, tuple[int, str]]:
    con = get_conn()
    cur = con.cursor()
    cur.execute("SELECT resident_id, taken, hm FROM meds WHERE ymd=? AND slot=?;", (ymd, slot))
    rows = cur.fetchall()
    con.close()
    out: dict[int, tuple[int, str]] = {}
    for rid, taken, hm in rows:
        out[int(rid)] = (int(taken), str(hm))
    return out


def get_patrol_map(ymd: str, round_name: str) -> dict[int, tuple[str, int, str]]:
    con = get_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT resident_id, state, safety_ok, hm FROM patrols WHERE ymd=? AND round=?;",
        (ymd, round_name),
    )
    rows = cur.fetchall()
    con.close()
    out: dict[int, tuple[str, int, str]] = {}
    for rid, state, okv, hm in rows:
        out[int(rid)] = (str(state), int(okv), str(hm))
    return out


# =========================
# Helpers
# =========================
def today_ymd():
    return datetime.now().strftime("%Y-%m-%d")


def now_hm():
    return datetime.now().strftime("%H:%M")


def default_slot_by_time():
    h = datetime.now().hour
    if 5 <= h < 11:
        return "朝"
    if 15 <= h < 20:
        return "夕"
    return "その他"


def parse_hm(hm: str):
    try:
        h, m = hm.split(":")
        return int(h), int(m)
    except Exception:
        n = datetime.now()
        return n.hour, n.minute


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _format_delta(value: float, unit: str, digits: int = 1) -> str:
    return f"{value:+.{digits}f}{unit}"


def _format_delta_int(value: int, unit: str = "") -> str:
    return f"{value:+d}{unit}"


# =========================
# Advice / Report (rule-based prototype)
# =========================
def advice_from_vitals(v: dict, prev_row: tuple | None):
    temp = float(v["temperature"])
    bh = int(v["bp_high"])
    bl = int(v["bp_low"])
    pulse = int(v["pulse"])
    spo2 = int(v["spo2"])
    rr = int(v["respiration"])
    cond = str(v["condition"])

    diffs = {}
    if prev_row:
        ptemp, pbh, pbl, ppulse, pspo2, prr, pcond = prev_row
        diffs["temp"] = temp - float(ptemp)
        diffs["bh"] = bh - int(pbh)
        diffs["bl"] = bl - int(pbl)
        diffs["pulse"] = pulse - int(ppulse)
        diffs["spo2"] = spo2 - int(pspo2)
        diffs["rr"] = rr - int(prr)
        diffs["cond_changed"] = 1 if (str(pcond) != cond) else 0
    else:
        diffs = {"temp": 0.0, "bh": 0, "bl": 0, "pulse": 0, "spo2": 0, "rr": 0, "cond_changed": 0}

    flags: list[str] = []
    warn: list[str] = []
    watch: list[str] = []
    obs: list[str] = []

    if spo2 <= 93:
        warn.append("SpO2が低め（≤93%）。呼吸状態の再評価、体位調整、報告検討。")
    elif spo2 <= 95:
        watch.append("SpO2やや低め（94-95%）。訴え/体位の確認、経過観察。")

    if bh >= 160 or bl >= 100:
        watch.append("血圧高め。頭痛/嘔気/興奮/不安など確認。")
    elif bh <= 90 or bl <= 60:
        watch.append("血圧低め。起立性低血圧・転倒に注意。")

    if temp >= 37.5:
        watch.append("発熱傾向。水分・安静、症状観察、必要時報告。")
    elif temp <= 35.5:
        watch.append("体温低め。保温・循環/栄養状態に留意。")

    if pulse >= 110:
        watch.append("脈拍速め。不安/疼痛/発熱/脱水/興奮の可能性。")
    elif pulse <= 45:
        watch.append("脈拍遅め。めまい/失神/冷汗に注意。")

    if rr >= 26:
        watch.append("呼吸数多め。苦しさやSpO2低下があれば早めに報告。")

    if prev_row:
        if diffs["bh"] >= 20:
            warn.append(f"前回比：血圧（上）が急上昇（{_format_delta_int(int(diffs['bh']))}）。再測定推奨。")
        if diffs["bh"] <= -20:
            warn.append(f"前回比：血圧（上）が急低下（{_format_delta_int(int(diffs['bh']))}）。転倒注意。")
        if diffs["temp"] >= 1.0:
            warn.append(f"前回比：体温が急上昇（{_format_delta(float(diffs['temp']), '℃', 1)}）。感染兆候に注意。")
        if diffs["spo2"] <= -3:
            warn.append(f"前回比：SpO2が低下（{_format_delta_int(int(diffs['spo2']), '%')}）。呼吸状態再評価。")
        if diffs.get("cond_changed", 0) == 1:
            watch.append("前回比：意識・活気が変化。普段との差を具体化して記録。")

    # condition観察
    if cond in ("活気なし", "傾眠"):
        obs.append("観察：呼名反応、表情、会話量、歩行ふらつき、食欲/水分、睡眠量。")
        obs.append("対応：訪室頻度UP、転倒リスク注意、必要時に報告。")
    elif cond in ("興奮", "不穏"):
        obs.append("観察：刺激要因、訴え、環境（騒音/照明）、対人トラブル兆候。")
        obs.append("対応：安心確保、声かけ簡潔、危険物/転倒リスク確認、必要時報告。")
    elif cond == "疼痛疑い":
        obs.append("観察：痛み部位/表情、動作時の嫌がり、発汗、バイタル変動。")
        obs.append("対応：無理な動作回避、体位調整、報告検討。")
    else:
        obs.append("観察：普段通りか（表情/会話/睡眠/訴え）、転倒リスク、服薬・水分状況。")

    if len(warn) >= 1:
        flags.append("watch")

    # urgent条件（要件：urgent時は自動で申し送り追記）
    if spo2 <= 92 or (temp >= 38.5 and cond in ("活気なし", "傾眠")):
        flags.append("urgent")

    if not warn and not watch:
        summary = "全体的に安定。通常通りの見守りでOK。"
    else:
        top = []
        if warn:
            top.append("要注意：" + warn[0])
        elif watch:
            top.append("観察：" + watch[0])
        if len(top) < 2 and watch:
            top.append("観察：" + watch[0])
        summary = " / ".join(top[:2])

    lines: list[str] = []
    if warn:
        lines.append("【注意/警告】")
        for s in warn[:4]:
            lines.append(f"- {s}")
    if watch:
        lines.append("【要観察】")
        for s in watch[:4]:
            lines.append(f"- {s}")
    if obs:
        lines.append("【観察ポイント】")
        for s in obs[:4]:
            lines.append(f"- {s}")

    detail = "\n".join(lines).strip() if lines else "全体的に安定。通常通りの見守りでOK。"
    return {"summary": summary, "detail": detail, "flags": flags, "diffs": diffs}


def build_admin_report(*, staff_name: str, resident_name: str, resident_code: str, payload: dict, prev_row: tuple | None, advice: dict) -> str:
    slot = payload["slot"]
    hm = payload["hm"]
    ymd = payload["ymd"]

    if prev_row:
        ptemp, pbh, pbl, ppulse, pspo2, prr, pcond = prev_row
        dtemp = payload["temperature"] - float(ptemp)
        dbh = payload["bp_high"] - int(pbh)
        dbl = payload["bp_low"] - int(pbl)
        dpulse = payload["pulse"] - int(ppulse)
        dspo2 = payload["spo2"] - int(pspo2)
        drr = payload["respiration"] - int(prr)
        dcond = "(変化あり)" if str(pcond) != str(payload["condition"]) else ""
        diff_str = (
            f"体温{_format_delta(dtemp,'℃',1)} / "
            f"血圧上{_format_delta_int(dbh)}・下{_format_delta_int(dbl)} / "
            f"脈拍{_format_delta_int(dpulse)} / "
            f"SpO2{_format_delta_int(dspo2,'%')} / "
            f"呼吸{_format_delta_int(drr)} {dcond}"
        ).strip()
    else:
        diff_str = "前回データなし"

    urgency = "【至急】" if ("urgent" in advice.get("flags", [])) else "【報告】"
    staff = staff_name if (staff_name or "").strip() else "(未選択)"

    text = (
        f"{urgency} バイタル共有（{resident_name}：{resident_code}）\n"
        f"- 記録者：{staff}\n"
        f"- 日時：{ymd} {hm}（{slot}）\n"
        f"- バイタル：体温{payload['temperature']:.1f}℃ / 血圧{payload['bp_high']}/{payload['bp_low']} / "
        f"脈拍{payload['pulse']} / SpO2{payload['spo2']}% / 呼吸{payload['respiration']}\n"
        f"- 意識・活気：{payload['condition']}\n"
        f"- 前回比：{diff_str}\n"
        f"\n"
        f"■所見まとめ\n"
        f"{advice.get('summary','')}\n"
        f"\n"
        f"■観察・対応案\n"
        f"{advice.get('detail','')}\n"
        f"\n"
        f"■お願い\n"
        f"- 追加観察/再測定のタイミング、医療連携/家族連絡の要否をご指示ください。\n"
    )
    return text.strip()


# =========================
# UI helpers
# =========================
def card(title: str, inner: ft.Control):
    return ft.Container(
        bgcolor=CARD_BG,
        border_radius=20,
        padding=16,
        shadow=SHADOW,
        border=ft.Border.all(1, BORDER),
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Text(title, size=14, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                inner,
            ],
        ),
    )


def header_bar(title: str, right: ft.Control | None = None):
    return ft.Container(
        bgcolor=HEADER,
        padding=14,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(title, size=18, weight=ft.FontWeight.W_800, color="white"),
                right if right else ft.Container(width=1),
            ],
        ),
    )


def nav(page: ft.Page, route: str):
    page.run_task(page.push_route, route)


def _scroll_sign(e) -> int:
    dy = 0
    for k in ("delta_y", "scroll_delta_y", "dy", "scrollDeltaY"):
        if hasattr(e, k):
            try:
                dy = getattr(e, k) or 0
                break
            except Exception:
                pass
    if dy < 0:
        return +1
    if dy > 0:
        return -1
    return 0


# =========================
# Stepper（±クリックが確実に反映する版）
# =========================
def make_stepper_value(
    page: ft.Page,
    *,
    label: str,
    get_value,
    set_value,
    step,
    min_v,
    max_v,
    fmt,
    unit_text: str = "",
    swipe_threshold: float = 10.0,
    on_changed=None,
):
    value_text = ft.Text(fmt(get_value()), size=26, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    acc = {"dx": 0.0}

    def apply(delta_steps: int):
        v = get_value()
        nv = v + step * delta_steps
        nv = clamp(nv, min_v, max_v)

        if isinstance(step, float):
            s = str(step)
            if "." in s:
                digits = len(s.split(".")[1])
                nv = round(float(nv), digits)

        set_value(nv)
        value_text.value = fmt(get_value())
        if on_changed:
            on_changed(get_value())
        page.update()

    def on_minus(e):
        apply(-1)

    def on_plus(e):
        apply(+1)

    def on_pan_start(e):
        acc["dx"] = 0.0

    def on_pan_update(e):
        dx = float(getattr(e, "delta_x", 0) or 0)
        acc["dx"] += dx

        while acc["dx"] >= swipe_threshold:
            acc["dx"] -= swipe_threshold
            apply(+1)

        while acc["dx"] <= -swipe_threshold:
            acc["dx"] += swipe_threshold
            apply(-1)

    def on_scroll(e):
        s = _scroll_sign(e)
        if s != 0:
            apply(s)

    value_area = ft.GestureDetector(
        on_pan_start=on_pan_start,
        on_pan_update=on_pan_update,
        on_scroll=on_scroll,
        content=ft.Container(
            padding=ft.Padding(10, 6, 10, 6),
            border_radius=14,
            bgcolor=ft.Colors.BLACK12,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=6,
                controls=[
                    value_text,
                    ft.Text(unit_text, size=12, color=MUTED) if unit_text else ft.Container(width=0),
                ],
            ),
        ),
    )

    minus_btn = ft.IconButton(
        icon=ft.Icons.REMOVE,
        icon_size=16,
        on_click=lambda e: on_minus(e),  # ★確実にバインド
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), bgcolor=ft.Colors.WHITE),
        width=34,
        height=34,
    )
    plus_btn = ft.IconButton(
        icon=ft.Icons.ADD,
        icon_size=16,
        on_click=lambda e: on_plus(e),  # ★確実にバインド
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), bgcolor=ft.Colors.WHITE),
        width=34,
        height=34,
    )

    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(label, size=12, color=MUTED),
            ft.Row(spacing=8, controls=[minus_btn, value_area, plus_btn]),
        ],
    )


def make_drum_column(
    page: ft.Page,
    *,
    label: str,
    get_value,
    set_value,
    min_v: int,
    max_v: int,
    pad2: bool = True,
):
    def fmt(v):
        return f"{int(v):02d}" if pad2 else f"{int(v)}"

    value_text = ft.Text(fmt(get_value()), size=34, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    acc = {"dy": 0.0}

    def apply(delta: int):
        nv = int(get_value()) + delta
        nv = clamp(nv, min_v, max_v)
        set_value(int(nv))
        value_text.value = fmt(get_value())
        page.update()

    def on_up(e):
        apply(+1)

    def on_down(e):
        apply(-1)

    def on_pan_start(e):
        acc["dy"] = 0.0

    def on_pan_update(e):
        dy = float(getattr(e, "delta_y", 0) or 0)
        acc["dy"] += dy
        threshold = 10.0

        while acc["dy"] <= -threshold:
            acc["dy"] += threshold
            apply(+1)

        while acc["dy"] >= threshold:
            acc["dy"] -= threshold
            apply(-1)

    def on_scroll(e):
        s = _scroll_sign(e)
        if s != 0:
            apply(s)

    value_area = ft.GestureDetector(
        on_pan_start=on_pan_start,
        on_pan_update=on_pan_update,
        on_scroll=on_scroll,
        content=ft.Container(
            padding=ft.Padding(18, 10, 18, 10),
            border_radius=18,
            bgcolor=ft.Colors.BLACK12,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
                controls=[
                    ft.Text(label, size=12, color=MUTED),
                    value_text,
                ],
            ),
        ),
    )

    return ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.IconButton(
                icon=ft.Icons.KEYBOARD_ARROW_UP,
                icon_size=22,
                on_click=on_up,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=14), bgcolor=ft.Colors.WHITE),
            ),
            value_area,
            ft.IconButton(
                icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                icon_size=22,
                on_click=on_down,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=14), bgcolor=ft.Colors.WHITE),
            ),
        ],
    )


def open_time_picker_sheet(page: ft.Page, *, title: str, initial_hm: str, on_decide):
    h0, m0 = parse_hm(initial_hm)
    tmp = {"h": h0, "m": m0}
    sheet_holder = {"bs": None}

    def set_h(v):
        tmp["h"] = int(v)

    def set_m(v):
        tmp["m"] = int(v)

    def get_h():
        return int(tmp["h"])

    def get_m():
        return int(tmp["m"])

    preview = ft.Text(f"{get_h():02d}:{get_m():02d}", size=22, weight=ft.FontWeight.W_900, color=TEXT_DARK)

    def refresh_preview():
        preview.value = f"{get_h():02d}:{get_m():02d}"
        page.update()

    def now_btn_in_sheet(e):
        n = datetime.now()
        set_h(n.hour)
        set_m(n.minute)
        refresh_preview()

    def close_sheet(e=None):
        bs = sheet_holder.get("bs")
        if bs is not None:
            bs.open = False
            page.update()

    def ok(e):
        hm = f"{get_h():02d}:{get_m():02d}"
        on_decide(hm)
        close_sheet()

    hour_col = make_drum_column(page, label="時", get_value=get_h, set_value=set_h, min_v=0, max_v=23, pad2=True)
    min_col = make_drum_column(page, label="分", get_value=get_m, set_value=set_m, min_v=0, max_v=59, pad2=True)

    bs = ft.BottomSheet(
        content=ft.Container(
            bgcolor="white",
            padding=16,
            border_radius=20,
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(title, size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                            ft.IconButton(icon=ft.Icons.CLOSE, on_click=close_sheet),
                        ],
                    ),
                    ft.Container(
                        padding=12,
                        border_radius=16,
                        bgcolor=ft.Colors.BLACK12,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER),
                                ft.Container(width=8),
                                preview,
                            ],
                        ),
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[hour_col, min_col],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.TextButton("キャンセル", on_click=close_sheet),
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.FilledButton("いま", on_click=now_btn_in_sheet),
                                    ft.FilledButton("決定", on_click=ok),
                                ],
                            ),
                        ],
                    ),
                    ft.Text("操作：▲/▼・マウスホイール・縦スワイプで調整できます。", size=11, color=MUTED),
                ],
            ),
        ),
        open=False,
    )

    if bs not in page.overlay:
        page.overlay.append(bs)
    sheet_holder["bs"] = bs
    bs.open = True
    page.update()


# =========================
# 定型文（自動転記）
# =========================
def build_meal_transcription(hm: str, slot: str, amount: int) -> str:
    meal_label = {"朝": "朝食", "昼": "昼食", "夕": "夕食"}.get(slot, f"{slot}食")
    if int(amount) >= 10:
        return f"{hm} {meal_label} 10/10 完食"
    return f"{hm} {meal_label} {int(amount)}/10"


def build_meds_transcription(hm: str, slot: str, taken: int) -> str:
    st = "服薬済" if int(taken) == 1 else "未"
    return f"{hm} {slot} 服薬 {st}"


def build_patrol_transcription(hm: str, round_name: str, state: str, safety_ok: int) -> str:
    ok = "安全OK" if int(safety_ok) == 1 else "安全未"
    return f"{hm} {round_name} 巡視 {state} / {ok}"


# =========================
# Views
# =========================
def view_login(page, app):
    id_tf = ft.TextField(label="ID", value="", width=APP_WIDTH - 60)
    pw_tf = ft.TextField(label="パスワード", password=True, can_reveal_password=True, width=APP_WIDTH - 60)

    def do_login(e):
        nav(page, "/staff")

    content = ft.Container(
        width=APP_WIDTH,
        alignment=ft.Alignment(0, 0),
        content=ft.Container(
            bgcolor="white",
            border_radius=20,
            padding=20,
            shadow=SHADOW,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("夜勤支援・意思決定サポート（プロトタイプ）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                    ft.Text("ログイン（モック）", size=13, color=MUTED),
                    id_tf,
                    pw_tf,
                    ft.FilledButton("ログイン", on_click=do_login),
                ],
            ),
        ),
    )

    body = ft.Container(bgcolor=BG, expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[content]))
    return ft.View(route="/login", controls=[body], bgcolor=BG)


def view_staff(page, app):
    def pick_staff(name):
        def _h(e):
            app["staff_name"] = name
            con = get_conn()
            cur = con.cursor()
            cur.execute("INSERT INTO staff_sessions (staff_name, ts) VALUES (?, ?);", (name, datetime.now().isoformat(timespec="seconds")))
            con.commit()
            con.close()
            nav(page, "/menu")
        return _h

    cards = []
    for s in STAFFS:
        cards.append(
            ft.Container(
                border_radius=16,
                padding=12,
                bgcolor="white",
                shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                border=ft.Border.all(1, BORDER),
                on_click=pick_staff(s),
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PERSON, size=18, color=HEADER),
                        ft.Text(s, size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ],
                ),
            )
        )

    grid = ft.GridView(
        expand=1,
        max_extent=180,
        child_aspect_ratio=2.4,
        spacing=10,
        run_spacing=10,
        controls=cards,
    )

    panel = ft.Container(
        width=APP_WIDTH,
        bgcolor="white",
        border_radius=20,
        padding=16,
        shadow=SHADOW,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Text("職員選択（1ユニット）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                ft.Text("タップしてログイン状態にします。", size=12, color=MUTED),
                ft.Container(height=520, content=grid),
                ft.FilledButton("戻る", on_click=lambda e: nav(page, "/login")),
            ],
        ),
    )

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[
                header_bar("職員選択"),
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]),
            ],
        ),
    )
    return ft.View(route="/staff", controls=[body], bgcolor=BG)


def view_menu(page, app):
    tiles = [
        ("申し送り", "/handover", ft.Icons.CAMPAIGN),
        ("バイタル", "/vitals", ft.Icons.FAVORITE),
        ("経過記録", "/progress", ft.Icons.NOTE_ALT),
        ("特記事項", "/special", ft.Icons.WARNING_AMBER),
        ("入浴", "/bath", ft.Icons.BATHTUB),
        ("食事", "/meal", ft.Icons.RESTAURANT),
        ("服薬", "/meds", ft.Icons.MEDICATION),
        ("巡視", "/patrol", ft.Icons.VISIBILITY),
    ]

    tile_controls = []
    for label, route, icon in tiles:
        tile_controls.append(
            ft.Container(
                border_radius=18,
                padding=14,
                bgcolor="white",
                border=ft.Border.all(1, BORDER),
                shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                on_click=lambda e, r=route: nav(page, r),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        ft.Icon(icon, size=26, color=HEADER),
                        ft.Text(label, size=13, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                    ],
                ),
            )
        )

    grid = ft.GridView(
        expand=1,
        max_extent=180,
        child_aspect_ratio=1.15,
        spacing=12,
        run_spacing=12,
        controls=tile_controls,
    )

    staff_bar = ft.Container(
        width=APP_WIDTH,
        padding=10,
        bgcolor="white",
        border_radius=14,
        border=ft.Border.all(1, BORDER),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(f"ログイン中：{app.get('staff_name','(未選択)')}", size=12, color=TEXT_DARK),
                ft.TextButton("ログアウト", on_click=lambda e: nav(page, "/login")),
            ],
        ),
    )

    panel = ft.Container(
        width=APP_WIDTH,
        bgcolor="white",
        border_radius=20,
        padding=16,
        shadow=SHADOW,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text("メインメニュー", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                ft.Container(height=520, content=grid),
                staff_bar,
            ],
        ),
    )

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[
                header_bar("ホーム"),
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]),
            ],
        ),
    )
    return ft.View(route="/menu", controls=[body], bgcolor=BG)


def view_handover(page, app):
    tf = ft.TextField(
        label="申し送り（自由入力）",
        multiline=True,
        min_lines=4,
        max_lines=8,
        hint_text="例：夜間は●●さん不穏、巡視増やす。/ Aさん発熱傾向あり、看護連携。",
    )
    slot_dd = ft.Dropdown(
        label="区分",
        options=[ft.dropdown.Option(s) for s in SLOTS],
        value=default_slot_by_time(),
        width=160,
    )

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    lv = ft.ListView(spacing=10, expand=True, padding=ft.Padding(12, 12, 12, 12))

    def reload():
        lv.controls.clear()
        con = get_conn()
        cur = con.cursor()
        if _has_column(con, "handover_notes", "staff_name"):
            cur.execute(
                """
                SELECT id, ts, ymd, slot, hm, text, level, likes, staff_name
                FROM handover_notes
                ORDER BY ts DESC
                LIMIT 80;
                """
            )
        else:
            cur.execute(
                """
                SELECT id, ts, ymd, slot, hm, text, level, likes
                FROM handover_notes
                ORDER BY ts DESC
                LIMIT 80;
                """
            )
        rows = cur.fetchall()
        con.close()

        if not rows:
            lv.controls.append(ft.Text("まだ申し送りがありません。", color=MUTED))
        else:
            for row in rows:
                if len(row) == 9:
                    note_id, ts, ymd, slot, hm, text, level, likes, staff_name = row
                else:
                    note_id, ts, ymd, slot, hm, text, level, likes = row
                    staff_name = ""

                badge = "【特】" if level == "special" else ("【至急】" if level == "urgent" else "")

                def like_handler(e, nid=int(note_id)):
                    inc_handover_like(nid)
                    reload()
                    show_snack("いいね！しました")

                like_row = ft.Row(
                    spacing=6,
                    controls=[
                        ft.IconButton(icon=ft.Icons.THUMB_UP_ALT, icon_size=18, on_click=like_handler),
                        ft.Text(str(int(likes)), size=12, color=MUTED),
                    ],
                )

                lv.controls.append(
                    ft.Container(
                        bgcolor="white",
                        border_radius=16,
                        padding=12,
                        border=ft.Border.all(1, BORDER),
                        shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.BLACK12, offset=ft.Offset(0, 3)),
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Text(f"{badge}{ymd} {hm}（{slot}）", size=12, color=MUTED),
                                        like_row,
                                    ],
                                ),
                                ft.Text(text, size=13, color=TEXT_DARK),
                                ft.Text(f"記録者：{staff_name or '(未記録)'}", size=11, color=MUTED),
                            ],
                        ),
                    )
                )
        page.update()

    def save_note(e):
        if not (tf.value or "").strip():
            show_snack("内容が空です")
            return
        ymd = today_ymd()
        slot = slot_dd.value or default_slot_by_time()
        hm = now_hm()
        ts = datetime.now().isoformat(timespec="seconds")
        add_handover_note(ymd, slot, hm, ts, tf.value.strip(), level="normal", staff_name=app.get("staff_name", ""))
        tf.value = ""
        reload()
        show_snack("申し送りを保存しました")

    reload()

    panel = ft.Container(
        width=APP_WIDTH,
        expand=True,
        bgcolor=BG,
        content=ft.Column(
            expand=True,
            spacing=12,
            controls=[
                ft.Container(
                    bgcolor="white",
                    border_radius=18,
                    padding=14,
                    shadow=SHADOW,
                    border=ft.Border.all(1, BORDER),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text("申し送り（自由入力）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                                    ft.TextButton("更新", on_click=lambda e: reload()),
                                ],
                            ),
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[slot_dd, ft.FilledButton("保存", on_click=save_note)],
                            ),
                            tf,
                            ft.Text("※urgent（急変）や特記事項は自動でここにも転記されます。", size=11, color=MUTED),
                        ],
                    ),
                ),
                ft.Container(expand=True, content=lv),
                ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu")),
            ],
        ),
    )

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[
                header_bar("申し送り", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))),
                ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel])),
            ],
        ),
    )
    return ft.View(route="/handover", controls=[body], bgcolor=BG)


def view_progress(page, app):
    state = {"resident_idx": 0, "filter_days": 3}
    resident_text = ft.Text("", size=14, weight=ft.FontWeight.W_800, color=TEXT_DARK)
    resident_sheet = {"bs": None}
    lv = ft.ListView(spacing=10, expand=True, padding=ft.Padding(12, 12, 12, 12))
    report_cache = {"text": ""}

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    def refresh_top():
        r = RESIDENTS[state["resident_idx"]]
        resident_text.value = f"{r['name']}（{r['code']}）"
        page.update()

    def open_resident_picker(e=None):
        def close_sheet(ev=None):
            bs = resident_sheet.get("bs")
            if bs is not None:
                bs.open = False
                page.update()

        def pick_idx(idx: int):
            def _h(ev):
                state["resident_idx"] = idx
                refresh_top()
                reload()
                close_sheet()
            return _h

        items: list[ft.Control] = []
        for i, r in enumerate(RESIDENTS):
            is_current = (i == state["resident_idx"])
            items.append(
                ft.Container(
                    border_radius=14,
                    padding=12,
                    bgcolor=HEADER if is_current else "white",
                    border=ft.Border.all(1, BORDER),
                    on_click=pick_idx(i),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color="white" if is_current else TEXT_DARK),
                            ft.Text(r["name"], size=12, color="white" if is_current else MUTED),
                        ],
                    ),
                )
            )

        bs = ft.BottomSheet(
            content=ft.Container(
                bgcolor="white",
                padding=16,
                border_radius=20,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("利用者を選択", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                                ft.IconButton(icon=ft.Icons.CLOSE, on_click=close_sheet),
                            ],
                        ),
                        ft.Container(height=420, content=ft.ListView(spacing=8, controls=items)),
                    ],
                ),
            ),
            open=False,
        )

        prev = resident_sheet.get("bs")
        if prev is not None:
            prev.open = False

        if bs not in page.overlay:
            page.overlay.append(bs)

        resident_sheet["bs"] = bs
        bs.open = True
        page.update()

    def reload():
        lv.controls.clear()
        rid = RESIDENTS[state["resident_idx"]]["id"]

        where = "WHERE resident_id=?"
        params = [rid]
        if state["filter_days"] is not None:
            d = datetime.now() - timedelta(days=int(state["filter_days"]))
            where += " AND ts >= ?"
            params.append(d.isoformat(timespec="seconds"))

        con = get_conn()
        cur = con.cursor()

        has_staff = _has_column(con, "support_logs", "staff_name")
        if has_staff:
            cur.execute(
                f"""
                SELECT ts, ymd, slot, hm, text, staff_name
                FROM support_logs
                {where}
                ORDER BY ts DESC
                LIMIT 120;
                """,
                tuple(params),
            )
        else:
            cur.execute(
                f"""
                SELECT ts, ymd, slot, hm, text
                FROM support_logs
                {where}
                ORDER BY ts DESC
                LIMIT 120;
                """,
                tuple(params),
            )

        rows = cur.fetchall()
        con.close()

        if not rows:
            lv.controls.append(ft.Text("まだ経過記録がありません。", color=MUTED))
        else:
            for row in rows:
                if has_staff:
                    ts, ymd, slot, hm, text, staff_name = row
                else:
                    ts, ymd, slot, hm, text = row
                    staff_name = ""
                lv.controls.append(
                    ft.Container(
                        bgcolor="white",
                        border_radius=16,
                        padding=12,
                        border=ft.Border.all(1, BORDER),
                        shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.BLACK12, offset=ft.Offset(0, 3)),
                        content=ft.Column(
                            spacing=4,
                            controls=[
                                ft.Text(f"{ymd} {hm}（{slot}）", size=12, color=MUTED),
                                ft.Text(text, size=13, color=TEXT_DARK),
                                ft.Text(f"記録者：{staff_name or '(未記録)'}", size=11, color=MUTED),
                            ],
                        ),
                    )
                )
        page.update()

    def set_days(days: int | None):
        state["filter_days"] = days
        reload()

    def _collect_recent_logs_text(resident_id: int, days: int = 1, limit: int = 15) -> list[str]:
        con = get_conn()
        cur = con.cursor()
        d = datetime.now() - timedelta(days=days)
        cur.execute(
            """
            SELECT ymd, hm, slot, text
            FROM support_logs
            WHERE resident_id=? AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?;
            """,
            (resident_id, d.isoformat(timespec="seconds"), int(limit)),
        )
        rows = cur.fetchall()
        con.close()
        out = []
        for ymd, hm, slot, text in rows:
            out.append(f"- {ymd} {hm}（{slot}） {text}")
        return out

    def generate_ai_report(e=None):
        """
        “AI”と名付けたルールベース報告案。
        ※将来 OpenAI 等へ差し替え前提で、現場で使える「貼れる」文章を生成。
        """
        r = RESIDENTS[state["resident_idx"]]
        rid = r["id"]
        staff = app.get("staff_name", "") or "(未選択)"

        lines = _collect_recent_logs_text(rid, days=1, limit=12)
        body = "\n".join(lines) if lines else "- 本日分の経過記録はまだありません。"

        report = (
            f"【報告案】（経過記録まとめ）\n"
            f"- 対象：{r['name']}（{r['code']}）\n"
            f"- 作成者：{staff}\n"
            f"- 作成時刻：{today_ymd()} {now_hm()}\n"
            f"\n"
            f"■本日（直近）の経過要点\n"
            f"{body}\n"
            f"\n"
            f"■申し送り（案）\n"
            f"- 重要事項があれば追記してください（不穏/転倒/発熱/SpO2低下など）。\n"
        ).strip()

        report_cache["text"] = report
        open_report_dialog(report)

    def open_report_dialog(report_text: str):
        report_tf = ft.TextField(value=report_text, multiline=True, min_lines=10, max_lines=16, read_only=True)

        def do_copy(ev):
            ok = False
            try:
                if hasattr(page, "set_clipboard"):
                    page.set_clipboard(report_text)
                    ok = True
            except Exception:
                ok = False
            show_snack("コピーしました" if ok else "コピー未対応環境です（選択してコピーしてください）")

        def close(ev=None):
            page.dialog.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("AI報告案（貼り付け用）"),
            content=ft.Container(width=520, content=report_tf),
            actions=[ft.TextButton("閉じる", on_click=close), ft.FilledButton("コピー", on_click=do_copy)],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def transfer_report_to_handover(e=None):
        text = (report_cache.get("text") or "").strip()
        if not text:
            show_snack("先に『AI報告案を生成』してください")
            return
        ymd = today_ymd()
        slot = default_slot_by_time()
        hm = now_hm()
        ts = datetime.now().isoformat(timespec="seconds")
        add_handover_note(ymd, slot, hm, ts, text, level="normal", staff_name=app.get("staff_name", ""))
        show_snack("報告案を申し送りへ転記しました")

    resident_picker = ft.Container(
        padding=ft.Padding(10, 10, 10, 10),
        border_radius=14,
        bgcolor=ft.Colors.BLACK12,
        on_click=open_resident_picker,
        content=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(ft.Icons.PERSON_SEARCH, size=18, color=HEADER),
                resident_text,
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=22, color=MUTED),
            ],
        ),
    )

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[ft.Text("経過記録", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK), ft.TextButton("更新", on_click=lambda e: reload())],
                ),
                resident_picker,
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.OutlinedButton("今日", on_click=lambda e: set_days(1)),
                        ft.OutlinedButton("直近3日", on_click=lambda e: set_days(3)),
                        ft.OutlinedButton("直近7日", on_click=lambda e: set_days(7)),
                        ft.OutlinedButton("すべて", on_click=lambda e: set_days(None)),
                    ],
                ),
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.FilledButton("AI報告案を生成", on_click=generate_ai_report),
                        ft.OutlinedButton("報告案を“申し送り”へ一括転記", on_click=transfer_report_to_handover),
                    ],
                ),
                ft.Text("※バイタル/食事/服薬/巡視の保存は自動でここに転記されます。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(
        width=APP_WIDTH,
        expand=True,
        bgcolor=BG,
        content=ft.Column(
            expand=True,
            spacing=12,
            controls=[top, ft.Container(expand=True, content=lv), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))],
        ),
    )

    refresh_top()
    reload()

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[header_bar("経過記録", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))],
        ),
    )
    return ft.View(route="/progress", controls=[body], bgcolor=BG)


def view_special(page, app):
    state = {"resident_idx": 0, "slot": default_slot_by_time(), "hm": now_hm(), "ymd": today_ymd()}
    resident_text = ft.Text("", size=14, weight=ft.FontWeight.W_800, color=TEXT_DARK)
    ymd_text = ft.Text("", size=12, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text("", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    title_text = ft.Text("特記事項", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK)

    tf = ft.TextField(
        label="特記事項（ここに入力）",
        multiline=True,
        min_lines=6,
        max_lines=10,
        hint_text="例：普段と違う言動、転倒、発熱、服薬拒否、強い不安、苦情など。",
    )

    def on_tf_change(e):
        title_text.color = ft.Colors.RED if (tf.value or "").strip() else TEXT_DARK
        page.update()

    tf.on_change = on_tf_change

    slot_dd = ft.Dropdown(label="区分", options=[ft.dropdown.Option(s) for s in SLOTS], value=state["slot"], width=160)
    resident_sheet = {"bs": None}

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    def refresh_top():
        r = RESIDENTS[state["resident_idx"]]
        resident_text.value = f"{r['name']}（{r['code']}）"
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        page.update()

    def open_resident_picker(e=None):
        def close_sheet(ev=None):
            bs = resident_sheet.get("bs")
            if bs is not None:
                bs.open = False
                page.update()

        def pick_idx(idx: int):
            def _h(ev):
                state["resident_idx"] = idx
                refresh_top()
                close_sheet()
            return _h

        items: list[ft.Control] = []
        for i, r in enumerate(RESIDENTS):
            is_current = (i == state["resident_idx"])
            items.append(
                ft.Container(
                    border_radius=14,
                    padding=12,
                    bgcolor=HEADER if is_current else "white",
                    border=ft.Border.all(1, BORDER),
                    on_click=pick_idx(i),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color="white" if is_current else TEXT_DARK),
                            ft.Text(r["name"], size=12, color="white" if is_current else MUTED),
                        ],
                    ),
                )
            )

        bs = ft.BottomSheet(
            content=ft.Container(
                bgcolor="white",
                padding=16,
                border_radius=20,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[ft.Text("利用者を選択", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK), ft.IconButton(icon=ft.Icons.CLOSE, on_click=close_sheet)],
                        ),
                        ft.Container(height=420, content=ft.ListView(spacing=8, controls=items)),
                    ],
                ),
            ),
            open=False,
        )

        prev = resident_sheet.get("bs")
        if prev is not None:
            prev.open = False

        if bs not in page.overlay:
            page.overlay.append(bs)

        resident_sheet["bs"] = bs
        bs.open = True
        page.update()

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), refresh_top()))

    def save_special(e):
        text = (tf.value or "").strip()
        if not text:
            show_snack("内容が空です")
            return

        rid = RESIDENTS[state["resident_idx"]]["id"]
        ymd = state["ymd"]
        slot = slot_dd.value or state["slot"]
        hm = state["hm"]
        ts = datetime.now().isoformat(timespec="seconds")
        staff = app.get("staff_name", "")

        add_progress_log(rid, ymd, slot, hm, ts, f"【特記事項】{text}", staff_name=staff, ai_sentiment="negative")
        add_handover_note(ymd, slot, hm, ts, f"【特記事項】{RESIDENTS[state['resident_idx']]['name']}：{text}", level="special", staff_name=staff)

        tf.value = ""
        on_tf_change(None)
        show_snack("特記事項を保存（申し送り＋経過記録へ転記）")

    resident_picker = ft.Container(
        padding=ft.Padding(10, 10, 10, 10),
        border_radius=14,
        bgcolor=ft.Colors.BLACK12,
        on_click=open_resident_picker,
        content=ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.PEOPLE, size=18, color=HEADER), resident_text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=22, color=MUTED)]),
    )

    time_row = ft.Container(
        border_radius=14,
        padding=10,
        bgcolor=ft.Colors.WHITE,
        border=ft.Border.all(1, BORDER),
        on_click=open_time_picker,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]),
                ft.Text("タップで変更", size=11, color=MUTED),
            ],
        ),
    )

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[title_text, ft.TextButton("今日", on_click=lambda e: (state.__setitem__("ymd", today_ymd()), refresh_top()))]),
                resident_picker,
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ymd_text, slot_dd]),
                time_row,
                tf,
                ft.FilledButton("保存（申し送り＋経過記録へ転記）", on_click=save_special),
                ft.Text("※ここで入力した内容は、申し送りと経過記録の両方に残ります。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(
        width=APP_WIDTH,
        expand=True,
        bgcolor=BG,
        content=ft.Column(
            expand=True,
            spacing=12,
            controls=[top, ft.FilledButton("申し送りを見る", on_click=lambda e: nav(page, "/handover")), ft.FilledButton("経過記録を見る", on_click=lambda e: nav(page, "/progress")), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))],
        ),
    )

    refresh_top()
    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[header_bar("特記事項", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))],
        ),
    )
    return ft.View(route="/special", controls=[body], bgcolor=BG)


def view_vitals(page, app):
    state = {
        "resident_idx": 0,
        "ymd": today_ymd(),
        "slot": default_slot_by_time(),
        "hm": now_hm(),
        "temperature": 36.5,
        "bp_high": 120,
        "bp_low": 80,
        "pulse": 70,
        "spo2": 97,
        "respiration": 18,
        "condition": "いつも通り",
    }

    resident_text = ft.Text("", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK)
    ymd_text = ft.Text("", size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text("", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    cond_big = ft.Text("", size=14, weight=ft.FontWeight.W_800, color=TEXT_DARK)

    slot_btns: dict[str, ft.TextButton] = {}
    resident_sheet = {"bs": None}
    last_report_cache = {"text": ""}

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    def refresh_top():
        r = RESIDENTS[state["resident_idx"]]
        resident_text.value = f"{r['name']}（{r['code']}）"
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        cond_big.value = f"意識・活気：{state['condition']}"

        for s in SLOTS:
            b = slot_btns.get(s)
            if b:
                b.style = ft.ButtonStyle(
                    bgcolor=HEADER if state["slot"] == s else "white",
                    color="white" if state["slot"] == s else TEXT_DARK,
                    shape=ft.RoundedRectangleBorder(radius=14),
                )

    def apply_and_update():
        refresh_top()
        page.update()

    def load_from_db():
        rid = RESIDENTS[state["resident_idx"]]["id"]
        con = get_conn()
        cur = con.cursor()
        # staff_name は読み込み不要（表示だけなら）
        cur.execute(
            """
            SELECT temperature, bp_high, bp_low, pulse, spo2, respiration, condition, hm
            FROM vitals
            WHERE resident_id=? AND ymd=? AND slot=?;
            """,
            (rid, state["ymd"], state["slot"]),
        )
        row = cur.fetchone()
        con.close()

        if row:
            state["temperature"] = float(row[0])
            state["bp_high"] = int(row[1])
            state["bp_low"] = int(row[2])
            state["pulse"] = int(row[3])
            state["spo2"] = int(row[4])
            state["respiration"] = int(row[5])
            state["condition"] = str(row[6])
            state["hm"] = str(row[7])
        else:
            state["hm"] = now_hm()

        apply_and_update()

    def prev_resident(e):
        state["resident_idx"] = (state["resident_idx"] - 1) % len(RESIDENTS)
        load_from_db()

    def next_resident(e):
        state["resident_idx"] = (state["resident_idx"] + 1) % len(RESIDENTS)
        load_from_db()

    def open_resident_grid_sheet(e=None):
        hm_map = get_vital_hm_map(state["ymd"], state["slot"])

        def close_sheet(ev=None):
            bs = resident_sheet.get("bs")
            if bs is not None:
                bs.open = False
                page.update()

        def pick_idx(idx: int):
            def _h(ev):
                state["resident_idx"] = idx
                load_from_db()
                close_sheet()
            return _h

        tiles: list[ft.Control] = []
        for i, r in enumerate(RESIDENTS):
            is_current = (i == state["resident_idx"])
            hm = hm_map.get(r["id"], "--:--")

            tiles.append(
                ft.Container(
                    border_radius=14,
                    padding=10,
                    bgcolor=HEADER if is_current else "white",
                    border=ft.Border.all(1, BORDER),
                    on_click=pick_idx(i),
                    content=ft.Column(
                        tight=True,
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color="white" if is_current else TEXT_DARK),
                            ft.Text(hm, size=11, weight=ft.FontWeight.W_700, color="white" if is_current else MUTED),
                        ],
                    ),
                )
            )

        grid = ft.GridView(
            controls=tiles,
            max_extent=90,
            child_aspect_ratio=1.15,
            spacing=10,
            run_spacing=10,
            height=420,
        )

        bs = ft.BottomSheet(
            content=ft.Container(
                bgcolor="white",
                padding=16,
                border_radius=20,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(f"利用者を一括選択（{state['ymd']} / {state['slot']}）", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                                ft.IconButton(icon=ft.Icons.CLOSE, on_click=close_sheet),
                            ],
                        ),
                        ft.Text("タップで即切替（右下の時刻は最終入力／'--:--'は未入力）", size=11, color=MUTED),
                        grid,
                    ],
                ),
            ),
            open=False,
        )

        prev = resident_sheet.get("bs")
        if prev is not None:
            prev.open = False

        if bs not in page.overlay:
            page.overlay.append(bs)

        resident_sheet["bs"] = bs
        bs.open = True
        page.update()

    def shift_date(days):
        state["ymd"] = (datetime.strptime(state["ymd"], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
        load_from_db()

    def prev_day(e):
        shift_date(-1)

    def today_btn(e):
        state["ymd"] = today_ymd()
        load_from_db()

    def next_day(e):
        shift_date(+1)

    def set_slot(slot):
        state["slot"] = slot
        state["hm"] = now_hm()
        load_from_db()

    def slot_click(slot):
        return lambda e: set_slot(slot)

    def slot_swipe(e):
        dx = getattr(e, "delta_x", 0) or 0
        if dx > 10:
            i = SLOTS.index(state["slot"])
            set_slot(SLOTS[(i - 1) % len(SLOTS)])
        elif dx < -10:
            i = SLOTS.index(state["slot"])
            set_slot(SLOTS[(i + 1) % len(SLOTS)])

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), apply_and_update()))

    def time_now_quick(e):
        state["hm"] = now_hm()
        apply_and_update()

    # condition（要件：選択肢を拡充）
    cond_dd = ft.Dropdown(
        label="意識・活気",
        options=[ft.dropdown.Option(c) for c in CONDITIONS],
        value=state["condition"],
        width=220,
    )

    def on_cond_change(e):
        state["condition"] = cond_dd.value or "いつも通り"
        apply_and_update()

    cond_dd.on_change = on_cond_change

    def open_report_dialog(report_text: str):
        report_tf = ft.TextField(value=report_text, multiline=True, min_lines=8, max_lines=14, read_only=True)

        def do_copy(ev):
            ok = False
            try:
                if hasattr(page, "set_clipboard"):
                    page.set_clipboard(report_text)
                    ok = True
            except Exception:
                ok = False
            show_snack("報告案をコピーしました" if ok else "コピー未対応環境です（選択してコピーしてください）")

        def close(ev=None):
            page.dialog.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("管理者・サビ管への報告案"),
            content=ft.Container(width=520, content=report_tf),
            actions=[ft.TextButton("閉じる", on_click=close), ft.FilledButton("コピー", on_click=do_copy)],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def make_report_now(e=None):
        try:
            ridx = state["resident_idx"]
            r = RESIDENTS[ridx]
            rid = r["id"]

            payload = {
                "resident_id": rid,
                "ymd": state["ymd"],
                "slot": state["slot"],
                "hm": state["hm"],
                "ts": datetime.now().isoformat(timespec="seconds"),
                "temperature": float(state["temperature"]),
                "bp_high": int(state["bp_high"]),
                "bp_low": int(state["bp_low"]),
                "pulse": int(state["pulse"]),
                "spo2": int(state["spo2"]),
                "respiration": int(state["respiration"]),
                "condition": state["condition"],
                "staff_name": app.get("staff_name", "") or "",
            }

            prev = get_prev_vitals(rid, state["ymd"], state["slot"])
            adv = advice_from_vitals(payload, prev)
            report = build_admin_report(
                staff_name=app.get("staff_name", ""),
                resident_name=r["name"],
                resident_code=r["code"],
                payload=payload,
                prev_row=prev,
                advice=adv,
            )
            last_report_cache["text"] = report
            open_report_dialog(report)
        except Exception as ex:
            show_snack(f"報告案の生成エラー: {ex}")

    def save(e):
        try:
            ridx = state["resident_idx"]
            r = RESIDENTS[ridx]
            rid = r["id"]
            ymd = state["ymd"]
            slot = state["slot"]
            hm = state["hm"]
            ts = datetime.now().isoformat(timespec="seconds")
            staff = app.get("staff_name", "") or ""

            payload = {
                "resident_id": rid,
                "ymd": ymd,
                "slot": slot,
                "hm": hm,
                "ts": ts,
                "temperature": float(state["temperature"]),
                "bp_high": int(state["bp_high"]),
                "bp_low": int(state["bp_low"]),
                "pulse": int(state["pulse"]),
                "spo2": int(state["spo2"]),
                "respiration": int(state["respiration"]),
                "condition": state["condition"],
                "staff_name": staff,
            }

            prev = get_prev_vitals(rid, ymd, slot)
            adv = advice_from_vitals(payload, prev)

            upsert_vitals(payload)

            if prev:
                ptemp, pbh, pbl, ppulse, pspo2, prr, pcond = prev
                dtemp = payload["temperature"] - float(ptemp)
                dbh = payload["bp_high"] - int(pbh)
                dbl = payload["bp_low"] - int(pbl)
                dpulse = payload["pulse"] - int(ppulse)
                dspo2 = payload["spo2"] - int(pspo2)
                drr = payload["respiration"] - int(prr)
                diff_str = (
                    f"体温{_format_delta(dtemp,'℃',1)} / "
                    f"血圧上{_format_delta_int(dbh)}・下{_format_delta_int(dbl)} / "
                    f"脈拍{_format_delta_int(dpulse)} / "
                    f"SpO2{_format_delta_int(dspo2,'%')} / "
                    f"呼吸{_format_delta_int(drr)}"
                )
            else:
                diff_str = "前回データなし"

            trans = (
                f"【バイタル】{slot} {hm}："
                f"体温{payload['temperature']:.1f}℃、"
                f"血圧{payload['bp_high']}/{payload['bp_low']}、"
                f"脈拍{payload['pulse']}、"
                f"SpO2 {payload['spo2']}%、"
                f"呼吸{payload['respiration']}。"
                f"意識状態：{payload['condition']}。"
            )

            full = (
                trans
                + "\n"
                + f"【前回比】{diff_str}"
                + "\n"
                + "【AIアドバイス（プロトタイプ）】"
                + "\n"
                + adv["detail"]
            )

            sentiment = "negative" if ("urgent" in adv.get("flags", []) or "watch" in adv.get("flags", [])) else None
            add_progress_log(rid, ymd, slot, hm, ts, full, staff_name=staff, ai_sentiment=sentiment)

            report = build_admin_report(
                staff_name=staff,
                resident_name=r["name"],
                resident_code=r["code"],
                payload=payload,
                prev_row=prev,
                advice=adv,
            )
            last_report_cache["text"] = report

            # ★要件：urgentならボタン不要で申し送りへ自動追記（ワンオペ支援）
            if "urgent" in adv.get("flags", []):
                add_handover_note(
                    ymd,
                    slot,
                    hm,
                    ts,
                    f"【至急】（自動）\n{report}",
                    level="urgent",
                    staff_name=staff,
                )
                show_snack(f"保存しました（至急）: {diff_str} → 申し送りへ自動追記")
            else:
                show_snack(f"保存しました（前回比: {diff_str}）")

        except Exception as ex:
            show_snack(f"保存エラー: {ex}")

    for s in SLOTS:
        slot_btns[s] = ft.TextButton(s, on_click=slot_click(s))

    resident_picker = ft.Container(
        padding=ft.Padding(10, 10, 10, 10),
        border_radius=14,
        bgcolor=ft.Colors.BLACK12,
        on_click=open_resident_grid_sheet,
        content=ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.PEOPLE, size=18, color=HEADER), resident_text, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=22, color=MUTED)]),
    )

    resident_box = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.TextButton("前へ", on_click=prev_resident), resident_picker, ft.TextButton("次へ", on_click=next_resident)]),
    )

    time_row = ft.Container(
        border_radius=14,
        padding=10,
        bgcolor=ft.Colors.WHITE,
        border=ft.Border.all(1, BORDER),
        on_click=open_time_picker,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]),
                ft.Row(spacing=6, controls=[ft.FilledButton("いま", on_click=time_now_quick), ft.Text("タップで変更", size=11, color=MUTED)]),
            ],
        ),
    )

    date_time_box = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[ft.Row(spacing=8, controls=[ft.TextButton("前日", on_click=prev_day), ft.TextButton("本日", on_click=today_btn), ft.TextButton("翌日", on_click=next_day)]), ymd_text],
                ),
                time_row,
            ],
        ),
    )

    slot_box = ft.GestureDetector(
        on_pan_update=slot_swipe,
        content=ft.Container(
            bgcolor="white",
            border_radius=18,
            padding=10,
            border=ft.Border.all(1, BORDER),
            shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
            content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_AROUND, controls=[slot_btns["朝"], slot_btns["夕"], slot_btns["その他"]]),
        ),
    )

    temp_row = make_stepper_value(
        page,
        label="体温",
        get_value=lambda: float(state["temperature"]),
        set_value=lambda v: state.__setitem__("temperature", float(v)),
        step=0.1,
        min_v=34.0,
        max_v=41.0,
        fmt=lambda v: f"{float(v):.1f}",
        unit_text="℃",
    )

    bh_row = make_stepper_value(
        page,
        label="血圧 上（収縮期）",
        get_value=lambda: int(state["bp_high"]),
        set_value=lambda v: state.__setitem__("bp_high", int(v)),
        step=1,
        min_v=70,
        max_v=200,
        fmt=lambda v: f"{int(v)}",
    )
    bl_row = make_stepper_value(
        page,
        label="血圧 下（拡張期）",
        get_value=lambda: int(state["bp_low"]),
        set_value=lambda v: state.__setitem__("bp_low", int(v)),
        step=1,
        min_v=40,
        max_v=130,
        fmt=lambda v: f"{int(v)}",
    )

    pulse_row = make_stepper_value(
        page,
        label="脈拍",
        get_value=lambda: int(state["pulse"]),
        set_value=lambda v: state.__setitem__("pulse", int(v)),
        step=1,
        min_v=30,
        max_v=150,
        fmt=lambda v: f"{int(v)}",
        unit_text="bpm",
    )

    spo2_row = make_stepper_value(
        page,
        label="SpO2",
        get_value=lambda: int(state["spo2"]),
        set_value=lambda v: state.__setitem__("spo2", int(v)),
        step=1,
        min_v=80,
        max_v=100,
        fmt=lambda v: f"{int(v)}",
        unit_text="%",
    )

    rr_row = make_stepper_value(
        page,
        label="呼吸数",
        get_value=lambda: int(state["respiration"]),
        set_value=lambda v: state.__setitem__("respiration", int(v)),
        step=1,
        min_v=10,
        max_v=40,
        fmt=lambda v: f"{int(v)}",
        unit_text="回/分",
    )

    condition_card = card(
        "意識・活気（選択肢拡充）",
        ft.Column(spacing=8, controls=[cond_big, cond_dd, ft.Text("※傾眠/興奮/不穏/疼痛疑い/いつも通り/活気なし", size=11, color=MUTED)]),
    )

    report_btn = ft.FilledButton("管理者・サビ管への報告案を作成（コピー用）", on_click=make_report_now)

    content_view = ft.ListView(
        expand=True,
        spacing=12,
        padding=ft.Padding(12, 12, 12, 12),
        controls=[
            resident_box,
            date_time_box,
            slot_box,
            card("体温（横スワイプ / ホイール / ＋－）", temp_row),
            card("血圧（横スワイプ / ホイール / ＋－）", ft.Column(spacing=10, controls=[bh_row, bl_row])),
            card("脈拍（横スワイプ / ホイール / ＋－）", pulse_row),
            card("SpO2（横スワイプ / ホイール / ＋－）", spo2_row),
            card("呼吸数（横スワイプ / ホイール / ＋－）", rr_row),
            condition_card,
            ft.Container(padding=ft.Padding(0, 6, 0, 0), content=ft.FilledButton("保存して記録", on_click=save)),
            ft.Container(padding=ft.Padding(0, 0, 0, 0), content=report_btn),
            ft.Container(padding=ft.Padding(0, 0, 0, 12), content=ft.FilledButton("経過記録を見る", on_click=lambda e: nav(page, "/progress"))),
            ft.Container(padding=ft.Padding(0, 0, 0, 12), content=ft.FilledButton("申し送りを見る", on_click=lambda e: nav(page, "/handover"))),
        ],
    )

    panel = ft.Container(width=APP_WIDTH, expand=True, bgcolor=BG, content=content_view)

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(
            spacing=0,
            controls=[header_bar("バイタル", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))],
        ),
    )

    apply_and_update()
    load_from_db()
    return ft.View(route="/vitals", controls=[body], bgcolor=BG)


# =========================
# 入浴 / 食事 / 服薬 / 巡視（自動転記＆記録者保存）
# =========================
def _date_nav_row(page, state, on_reload):
    def shift(days):
        state["ymd"] = (datetime.strptime(state["ymd"], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
        on_reload()

    return ft.Row(
        spacing=10,
        controls=[
            ft.TextButton("前日", on_click=lambda e: shift(-1)),
            ft.TextButton("本日", on_click=lambda e: (state.__setitem__("ymd", today_ymd()), on_reload())),
            ft.TextButton("翌日", on_click=lambda e: shift(+1)),
        ],
    )


def view_bath(page, app):
    state = {"ymd": today_ymd(), "hm": now_hm()}
    ymd_text = ft.Text(state["ymd"], size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text(state["hm"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    lv = ft.ListView(expand=True, spacing=12, padding=ft.Padding(12, 12, 12, 12))

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), _refresh_top()))

    def _refresh_top():
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        page.update()

    def reload():
        lv.controls.clear()
        _refresh_top()

        bath_map = get_bath_map(state["ymd"])
        staff = app.get("staff_name", "") or ""

        for r in RESIDENTS:
            rid = r["id"]
            st, last_hm = bath_map.get(rid, ("none", "--:--"))
            badge = "入浴" if st == "bath" else ("拒否" if st == "refuse" else "未")
            right = ft.Text(f"{badge} / {last_hm}", size=12, color=MUTED)

            def set_status(new_status: str, rid_=rid):
                def _h(e):
                    ts = datetime.now().isoformat(timespec="seconds")
                    upsert_bath(rid_, state["ymd"], state["hm"], ts, new_status, staff_name=staff)
                    reload()
                    show_snack("保存しました")
                return _h

            btn_bath = ft.FilledButton("入浴", on_click=set_status("bath"), style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16)))
            btn_ref = ft.OutlinedButton("拒否", on_click=set_status("refuse"))
            btn_none = ft.OutlinedButton("未", on_click=set_status("none"))

            if st == "bath":
                btn_bath.style = ft.ButtonStyle(bgcolor=HEADER, color="white", shape=ft.RoundedRectangleBorder(radius=16))
            if st == "refuse":
                btn_ref.style = ft.ButtonStyle(bgcolor=ft.Colors.BLACK12, shape=ft.RoundedRectangleBorder(radius=16))
            if st == "none":
                btn_none.style = ft.ButtonStyle(bgcolor=ft.Colors.BLACK12, shape=ft.RoundedRectangleBorder(radius=16))

            lv.controls.append(
                ft.Container(
                    bgcolor="white",
                    border_radius=18,
                    padding=14,
                    border=ft.Border.all(1, BORDER),
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[ft.Row(spacing=10, controls=[ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK), ft.Text(r["name"], size=12, color=MUTED)]), right],
                            ),
                            ft.Row(spacing=10, controls=[btn_bath, btn_ref, btn_none]),
                        ],
                    ),
                )
            )

        page.update()

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("入浴（時間 + 入浴/拒否/未）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK), ft.TextButton("更新", on_click=lambda e: reload())]),
                _date_nav_row(page, state, reload),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Container(), ymd_text]),
                ft.Container(
                    border_radius=14,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, BORDER),
                    on_click=open_time_picker,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]), ft.Text("タップで変更", size=11, color=MUTED)],
                    ),
                ),
                ft.Text("※各行ボタンで即保存。保存後はすぐに表示へ反映。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(width=APP_WIDTH, expand=True, bgcolor=BG, content=ft.Column(expand=True, spacing=12, controls=[top, ft.Container(expand=True, content=lv), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))]))
    reload()

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(spacing=0, controls=[header_bar("入浴", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))]),
    )
    return ft.View(route="/bath", controls=[body], bgcolor=BG)


def view_meal(page, app):
    state = {"ymd": today_ymd(), "hm": now_hm(), "slot": "朝"}
    ymd_text = ft.Text(state["ymd"], size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text(state["hm"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)

    slot_dd = ft.Dropdown(label="区分", options=[ft.dropdown.Option(s) for s in MEAL_SLOTS], value=state["slot"], width=160)
    lv = ft.ListView(expand=True, spacing=12, padding=ft.Padding(12, 12, 12, 12))

    def _refresh_top():
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        page.update()

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), _refresh_top()))

    def reload():
        lv.controls.clear()
        _refresh_top()

        slot = slot_dd.value or state["slot"]
        state["slot"] = slot
        meal_map = get_meal_map(state["ymd"], slot)
        staff = app.get("staff_name", "") or ""

        for r in RESIDENTS:
            rid = r["id"]
            amt, last_hm = meal_map.get(rid, (10, "--:--"))
            row_state = {"amt": int(amt)}

            right = ft.Text(f"{last_hm}", size=12, color=MUTED)

            def save_now(new_val: int, rid_=rid):
                ts = datetime.now().isoformat(timespec="seconds")
                upsert_meal(rid_, state["ymd"], slot, state["hm"], ts, int(new_val), staff_name=staff)

                # ★要件：食事保存時 → 経過記録へ自動転記
                text = build_meal_transcription(state["hm"], slot, int(new_val))
                add_progress_log(rid_, state["ymd"], default_slot_by_time(), state["hm"], ts, f"【食事】{text}", staff_name=staff)

                # 表示即反映
                reload()

            stepper = make_stepper_value(
                page,
                label="量（1〜10）",
                get_value=lambda rs=row_state: int(rs["amt"]),
                set_value=lambda v, rs=row_state: rs.__setitem__("amt", int(v)),
                step=1,
                min_v=1,
                max_v=10,
                fmt=lambda v: f"{int(v)}/10",
                on_changed=lambda v: save_now(v),
            )

            lv.controls.append(
                ft.Container(
                    bgcolor="white",
                    border_radius=18,
                    padding=14,
                    border=ft.Border.all(1, BORDER),
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[ft.Row(spacing=10, controls=[ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK), ft.Text(r["name"], size=12, color=MUTED)]), right],
                            ),
                            stepper,
                            ft.Text("※横スワイプ/ホイール/±で変更 → そのまま自動保存＆経過記録へ転記", size=11, color=MUTED),
                        ],
                    ),
                )
            )

        page.update()

    def on_slot_change(e):
        state["slot"] = slot_dd.value or "朝"
        reload()

    slot_dd.on_change = on_slot_change

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("食事（朝/昼/夕 × 量1〜10）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK), ft.TextButton("更新", on_click=lambda e: reload())]),
                _date_nav_row(page, state, reload),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[slot_dd, ymd_text]),
                ft.Container(
                    border_radius=14,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, BORDER),
                    on_click=open_time_picker,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]), ft.Text("タップで変更", size=11, color=MUTED)],
                    ),
                ),
                ft.Text("※量は変更した瞬間に保存＆経過記録へ定型文で転記されます。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(width=APP_WIDTH, expand=True, bgcolor=BG, content=ft.Column(expand=True, spacing=12, controls=[top, ft.Container(expand=True, content=lv), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))]))
    reload()

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(spacing=0, controls=[header_bar("食事", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))]),
    )
    return ft.View(route="/meal", controls=[body], bgcolor=BG)


def view_meds(page, app):
    state = {"ymd": today_ymd(), "hm": now_hm(), "slot": "朝"}
    ymd_text = ft.Text(state["ymd"], size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text(state["hm"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    slot_dd = ft.Dropdown(label="スロット", options=[ft.dropdown.Option(s) for s in MED_SLOTS], value=state["slot"], width=160)
    lv = ft.ListView(expand=True, spacing=12, padding=ft.Padding(12, 12, 12, 12))

    def show_snack(msg: str):
        page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=HEADER)
        page.snack_bar.open = True
        page.update()

    def _refresh_top():
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        page.update()

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), _refresh_top()))

    def reload():
        lv.controls.clear()
        _refresh_top()

        slot = slot_dd.value or state["slot"]
        state["slot"] = slot
        meds_map = get_meds_map(state["ymd"], slot)
        staff = app.get("staff_name", "") or ""

        for r in RESIDENTS:
            rid = r["id"]
            taken, last_hm = meds_map.get(rid, (0, "--:--"))
            badge = "服薬済" if int(taken) == 1 else "未"
            right = ft.Text(f"{badge} / {last_hm}", size=12, color=MUTED)

            def set_taken(val: int, rid_=rid):
                def _h(e):
                    ts = datetime.now().isoformat(timespec="seconds")
                    upsert_meds(rid_, state["ymd"], slot, state["hm"], ts, val, staff_name=staff)

                    # ★要件：服薬保存時 → 経過記録へ自動転記
                    text = build_meds_transcription(state["hm"], slot, val)
                    add_progress_log(rid_, state["ymd"], default_slot_by_time(), state["hm"], ts, f"【服薬】{text}", staff_name=staff)

                    reload()
                    show_snack("保存しました")
                return _h

            btn_ok = ft.FilledButton("服薬済", on_click=set_taken(1))
            btn_ng = ft.OutlinedButton("未", on_click=set_taken(0))

            if int(taken) == 1:
                btn_ok.style = ft.ButtonStyle(bgcolor=HEADER, color="white", shape=ft.RoundedRectangleBorder(radius=16))
            else:
                btn_ng.style = ft.ButtonStyle(bgcolor=ft.Colors.BLACK12, shape=ft.RoundedRectangleBorder(radius=16))

            lv.controls.append(
                ft.Container(
                    bgcolor="white",
                    border_radius=18,
                    padding=14,
                    border=ft.Border.all(1, BORDER),
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[ft.Row(spacing=10, controls=[ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK), ft.Text(r["name"], size=12, color=MUTED)]), right],
                            ),
                            ft.Row(spacing=10, controls=[btn_ok, btn_ng]),
                            ft.Text("※押した瞬間に保存＆経過記録へ定型文で転記", size=11, color=MUTED),
                        ],
                    ),
                )
            )

        page.update()

    def on_slot_change(e):
        state["slot"] = slot_dd.value or "朝"
        reload()

    slot_dd.on_change = on_slot_change

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("服薬（スロット × 済/未）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK), ft.TextButton("更新", on_click=lambda e: reload())]),
                _date_nav_row(page, state, reload),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[slot_dd, ymd_text]),
                ft.Container(
                    border_radius=14,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, BORDER),
                    on_click=open_time_picker,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]), ft.Text("タップで変更", size=11, color=MUTED)],
                    ),
                ),
                ft.Text("※各行で“済/未”を押すと即保存→経過記録へ転記。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(width=APP_WIDTH, expand=True, bgcolor=BG, content=ft.Column(expand=True, spacing=12, controls=[top, ft.Container(expand=True, content=lv), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))]))
    reload()

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(spacing=0, controls=[header_bar("服薬", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))]),
    )
    return ft.View(route="/meds", controls=[body], bgcolor=BG)


def view_patrol(page, app):
    state = {"ymd": today_ymd(), "hm": now_hm(), "round": "1回目"}
    ymd_text = ft.Text(state["ymd"], size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK)
    hm_text = ft.Text(state["hm"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    lv = ft.ListView(expand=True, spacing=12, padding=ft.Padding(12, 12, 12, 12))
    round_btns: dict[str, ft.TextButton] = {}

    def _refresh_top():
        ymd_text.value = state["ymd"]
        hm_text.value = state["hm"]
        for rn in PATROL_ROUNDS:
            b = round_btns.get(rn)
            if b:
                b.style = ft.ButtonStyle(bgcolor=HEADER if state["round"] == rn else "white", color="white" if state["round"] == rn else TEXT_DARK, shape=ft.RoundedRectangleBorder(radius=14))
        page.update()

    def open_time_picker(e=None):
        open_time_picker_sheet(page, title="時刻を選択", initial_hm=state["hm"], on_decide=lambda hm: (state.__setitem__("hm", hm), _refresh_top()))

    def set_round(rn: str):
        state["round"] = rn
        reload()

    def reload():
        lv.controls.clear()
        _refresh_top()

        pat_map = get_patrol_map(state["ymd"], state["round"])
        staff = app.get("staff_name", "") or ""

        for r in RESIDENTS:
            rid = r["id"]
            st, okv, last_hm = pat_map.get(rid, ("未", 0, "--:--"))
            ok_label = "安全OK" if int(okv) == 1 else "安全未"
            right = ft.Text(f"{st} / {ok_label} / {last_hm}", size=12, color=MUTED)

            def save_state(new_state: str, rid_=rid):
                def _h(e):
                    old = pat_map.get(rid_, ("未", 0, "--:--"))
                    old_ok = int(old[1])
                    ts = datetime.now().isoformat(timespec="seconds")
                    upsert_patrol(rid_, state["ymd"], state["round"], state["hm"], ts, new_state, old_ok, staff_name=staff)

                    # ★要件：巡視保存時 → 経過記録へ自動転記（定型文）
                    text = build_patrol_transcription(state["hm"], state["round"], new_state, old_ok)
                    add_progress_log(rid_, state["ymd"], default_slot_by_time(), state["hm"], ts, f"【巡視】{text}", staff_name=staff)

                    reload()
                return _h

            def save_ok(rid_=rid):
                def _h(e):
                    old = pat_map.get(rid_, ("未", 0, "--:--"))
                    old_state = str(old[0])
                    ts = datetime.now().isoformat(timespec="seconds")
                    upsert_patrol(rid_, state["ymd"], state["round"], state["hm"], ts, old_state, 1, staff_name=staff)

                    text = build_patrol_transcription(state["hm"], state["round"], old_state, 1)
                    add_progress_log(rid_, state["ymd"], default_slot_by_time(), state["hm"], ts, f"【巡視】{text}", staff_name=staff)

                    reload()
                return _h

            btns = []
            for s in PATROL_STATES:
                btn = ft.FilledButton("就寝", on_click=save_state("就寝")) if s == "就寝" else ft.OutlinedButton(s, on_click=save_state(s))
                if st == s:
                    btn.style = ft.ButtonStyle(bgcolor=HEADER, color="white", shape=ft.RoundedRectangleBorder(radius=16))
                btns.append(btn)

            btn_ok = ft.FilledButton("安全確認OK", on_click=save_ok())
            if int(okv) == 1:
                btn_ok.style = ft.ButtonStyle(bgcolor=HEADER, color="white", shape=ft.RoundedRectangleBorder(radius=16))

            lv.controls.append(
                ft.Container(
                    bgcolor="white",
                    border_radius=18,
                    padding=14,
                    border=ft.Border.all(1, BORDER),
                    shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Row(spacing=10, controls=[ft.Text(r["code"], size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK), ft.Text(r["name"], size=12, color=MUTED)]), right]),
                            ft.Row(spacing=10, controls=btns),
                            btn_ok,
                            ft.Text("※押した瞬間に保存＆経過記録へ定型文で転記", size=11, color=MUTED),
                        ],
                    ),
                )
            )

        page.update()

    for rn in PATROL_ROUNDS:
        round_btns[rn] = ft.TextButton(rn, on_click=lambda e, rnn=rn: set_round(rnn))

    round_box = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=10,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Row(alignment=ft.MainAxisAlignment.START, controls=[round_btns["1回目"], round_btns["2回目"]]),
    )

    top = ft.Container(
        bgcolor="white",
        border_radius=18,
        padding=12,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=10, color=ft.Colors.BLACK12, offset=ft.Offset(0, 4)),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("巡視（2回固定）", size=16, weight=ft.FontWeight.W_800, color=TEXT_DARK), ft.TextButton("更新", on_click=lambda e: reload())]),
                _date_nav_row(page, state, reload),
                round_box,
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Container(), ymd_text]),
                ft.Container(
                    border_radius=14,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, BORDER),
                    on_click=open_time_picker,
                    content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.SCHEDULE, size=18, color=HEADER), hm_text]), ft.Text("タップで変更", size=11, color=MUTED)]),
                ),
                ft.Text("※状態＋安全確認OKで運用。保存時は経過記録へも転記されます。", size=11, color=MUTED),
            ],
        ),
    )

    panel = ft.Container(width=APP_WIDTH, expand=True, bgcolor=BG, content=ft.Column(expand=True, spacing=12, controls=[top, ft.Container(expand=True, content=lv), ft.FilledButton("戻る", on_click=lambda e: nav(page, "/menu"))]))
    _refresh_top()
    reload()

    body = ft.Container(
        bgcolor=BG,
        expand=True,
        content=ft.Column(spacing=0, controls=[header_bar("巡視", ft.TextButton("戻る", on_click=lambda e: nav(page, "/menu"))), ft.Container(expand=True, content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[panel]))]),
    )
    return ft.View(route="/patrol", controls=[body], bgcolor=BG)


# =========================
# App main / routing
# =========================
def main(page: ft.Page):
    page.title = "Night Shift Decision Support Prototype"
    page.bgcolor = BG
    page.padding = 0

    try:
        page.window.width = 520
        page.window.height = 900
        page.window.resizable = True
    except Exception:
        pass

    # ★DROPしない。既存DBを活かしてMigrationする
    init_db_if_needed()

    app = {"staff_name": ""}

    def route_change(e):
        page.views.clear()
        route = page.route

        if route in ("/", "/login"):
            page.views.append(view_login(page, app))
        elif route == "/staff":
            page.views.append(view_staff(page, app))
        elif route == "/menu":
            page.views.append(view_menu(page, app))
        elif route == "/handover":
            page.views.append(view_handover(page, app))
        elif route == "/vitals":
            page.views.append(view_vitals(page, app))
        elif route == "/progress":
            page.views.append(view_progress(page, app))
        elif route == "/special":
            page.views.append(view_special(page, app))
        elif route == "/bath":
            page.views.append(view_bath(page, app))
        elif route == "/meal":
            page.views.append(view_meal(page, app))
        elif route == "/meds":
            page.views.append(view_meds(page, app))
        elif route == "/patrol":
            page.views.append(view_patrol(page, app))
        else:
            page.views.append(view_login(page, app))

        page.update()

    def view_pop(e: ft.ViewPopEvent):
        if e.view is not None and e.view in page.views:
            page.views.remove(e.view)
        top = page.views[-1] if page.views else None
        if top is not None:
            page.run_task(page.push_route, top.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    page.run_task(page.push_route, "/login")


if __name__ == "__main__":
    ft.run(main)
