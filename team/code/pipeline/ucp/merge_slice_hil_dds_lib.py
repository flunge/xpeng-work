"""
IPS DDS merge/slice library (logic aligned with new_code/merge_slice_hil_dds.py; not imported from that path).
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RECORDING_RE = re.compile(r"^recording_(\d+)_", re.IGNORECASE)
EXCLUDED_TABLE_PREFIXES = ("CameraVideoTopic",)


@dataclass
class MergeSliceResult:
    merged_dat_path: Path
    output_dir: Path
    out_dat_name: str
    min_timestamp: int
    max_timestamp: int


def default_output_dat_name(recording_index: int = 0) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    return f"recording_{int(recording_index)}_{stamp}.dat"


def qi(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def is_excluded_topic_table(name: str) -> bool:
    return any(name.startswith(p) for p in EXCLUDED_TABLE_PREFIXES)


def filter_tables_for_merge(tables: set[str] | list[str]) -> list[str]:
    return sorted(t for t in tables if not is_excluded_topic_table(t))


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-262144")
    conn.execute("PRAGMA temp_store=MEMORY")


def list_user_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    if schema == "main":
        sql = (
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    else:
        sql = (
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    return [row[0] for row in conn.execute(sql).fetchall()]


def sorted_recording_dats(input_dir: Path) -> list[Path]:
    dats = [
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix == ".dat" and "recording" in p.name.lower()
    ]
    if not dats:
        raise FileNotFoundError(f"未找到 recording_*.dat: {input_dir}")

    def sort_key(p: Path) -> tuple[int, str]:
        m = RECORDING_RE.match(p.name)
        if m:
            return (int(m.group(1)), p.name)
        return (10**9, p.name)

    return sorted(dats, key=sort_key)


def time_column_name(kind: str = "source") -> str:
    if kind == "reception":
        return "SampleInfo_reception_timestamp"
    return "SampleInfo_source_timestamp"


def merge_two_dat(path_a: Path, path_b: Path, out_path: Path, ts_col: str) -> None:
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    try:
        _apply_pragmas(conn)
        conn.execute("ATTACH DATABASE ? AS da", (str(path_a),))
        conn.execute("ATTACH DATABASE ? AS db", (str(path_b),))
        tables_a = set(list_user_tables(conn, "da"))
        tables_b = set(list_user_tables(conn, "db"))
        all_tables = filter_tables_for_merge(tables_a | tables_b)
        for t in all_tables:
            q = qi(t)
            in_a = t in tables_a
            in_b = t in tables_b
            if in_a and in_b:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM da.{q} WHERE 0")
                conn.execute(
                    f"INSERT INTO {q} SELECT * FROM da.{q} UNION ALL SELECT * FROM db.{q} ORDER BY {ts_col}"
                )
            elif in_a:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM da.{q} WHERE 0")
                conn.execute(f"INSERT INTO {q} SELECT * FROM da.{q}")
            else:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM db.{q} WHERE 0")
                conn.execute(f"INSERT INTO {q} SELECT * FROM db.{q}")
        conn.commit()
    finally:
        conn.close()


def merge_two_dat_filtered(
    path_a: Path, path_b: Path, out_path: Path, ts_col: str, t_lo: int, t_hi: int
) -> None:
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    try:
        _apply_pragmas(conn)
        conn.execute("ATTACH DATABASE ? AS da", (str(path_a),))
        conn.execute("ATTACH DATABASE ? AS db", (str(path_b),))
        tables_a = set(list_user_tables(conn, "da"))
        tables_b = set(list_user_tables(conn, "db"))
        all_tables = filter_tables_for_merge(tables_a | tables_b)
        filt = f"{ts_col} >= {t_lo} AND {ts_col} <= {t_hi}"
        for t in all_tables:
            q = qi(t)
            in_a = t in tables_a
            in_b = t in tables_b
            if in_a and in_b:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM da.{q} WHERE 0")
                conn.execute(
                    f"INSERT INTO {q} SELECT * FROM da.{q} WHERE {filt} "
                    f"UNION ALL SELECT * FROM db.{q} WHERE {filt}"
                )
            elif in_a:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM da.{q} WHERE 0")
                conn.execute(f"INSERT INTO {q} SELECT * FROM da.{q} WHERE {filt}")
            else:
                conn.execute(f"CREATE TABLE {q} AS SELECT * FROM db.{q} WHERE 0")
                conn.execute(f"INSERT INTO {q} SELECT * FROM db.{q} WHERE {filt}")
        conn.commit()
    finally:
        conn.close()


def merge_chain_filtered(
    dat_paths: list[Path], out_path: Path, ts_col: str, t_lo: int, t_hi: int
) -> None:
    if len(dat_paths) == 1:
        shutil.copy2(dat_paths[0], out_path)
        slice_dat(out_path, t_lo, t_hi, ts_col)
        return
    if len(dat_paths) == 2:
        merge_two_dat_filtered(dat_paths[0], dat_paths[1], out_path, ts_col, t_lo, t_hi)
        return
    tmp = Path(tempfile.mkdtemp(prefix="ips_merge_", dir=out_path.parent))
    try:
        current: Path = dat_paths[0]
        for idx in range(1, len(dat_paths)):
            nxt = dat_paths[idx]
            merged = tmp / f"step_{idx}.dat"
            if idx == len(dat_paths) - 1:
                merge_two_dat_filtered(current, nxt, merged, ts_col, t_lo, t_hi)
            else:
                merge_two_dat(current, nxt, merged, ts_col)
            if idx > 1 and current.exists():
                current.unlink(missing_ok=True)
            current = merged
        shutil.move(str(current), str(out_path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def localpose_bounds_in_window_merged(
    merged_path: Path, t_lo: int, t_hi: int, ts_col: str, localpose_table: str
) -> tuple[int, int] | None:
    conn = sqlite3.connect(str(merged_path))
    try:
        if localpose_table not in list_user_tables(conn, "main"):
            return None
        q = qi(localpose_table)
        row = conn.execute(
            f"SELECT MIN({ts_col}), MAX({ts_col}) FROM {q} WHERE {ts_col} >= ? AND {ts_col} <= ?",
            (t_lo, t_hi),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0]), int(row[1])
    finally:
        conn.close()


def localpose_bounds_in_window_dats(
    dats: list[Path], t_lo: int, t_hi: int, ts_col: str, localpose_table: str
) -> tuple[int, int] | None:
    mins: list[int] = []
    maxs: list[int] = []
    for p in dats:
        conn = sqlite3.connect(str(p))
        try:
            if localpose_table not in list_user_tables(conn, "main"):
                continue
            q = qi(localpose_table)
            row = conn.execute(
                f"SELECT MIN({ts_col}), MAX({ts_col}) FROM {q} WHERE {ts_col} >= ? AND {ts_col} <= ?",
                (t_lo, t_hi),
            ).fetchone()
            if row and row[0] is not None:
                mins.append(int(row[0]))
                maxs.append(int(row[1]))
        finally:
            conn.close()
    if not mins:
        return None
    return min(mins), max(maxs)


def slice_dat(path: Path, t_lo: int, t_hi: int, ts_col: str) -> None:
    conn = sqlite3.connect(str(path))
    try:
        _apply_pragmas(conn)
        tables = list_user_tables(conn, "main")
        for i, t in enumerate(tables):
            q = qi(t)
            if is_excluded_topic_table(t):
                conn.execute(f"DROP TABLE {q}")
                continue
            tmp = f"__ips_slice_{i}"
            conn.execute(
                f"CREATE TABLE {qi(tmp)} AS SELECT * FROM {q} WHERE {ts_col} >= ? AND {ts_col} <= ?",
                (t_lo, t_hi),
            )
            conn.execute(f"DROP TABLE {q}")
            conn.execute(f"ALTER TABLE {qi(tmp)} RENAME TO {q}")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()


def drop_excluded_topic_tables(path: Path) -> list[str]:
    dropped: list[str] = []
    conn = sqlite3.connect(str(path))
    try:
        _apply_pragmas(conn)
        for t in list_user_tables(conn, "main"):
            if is_excluded_topic_table(t):
                conn.execute(f"DROP TABLE {qi(t)}")
                dropped.append(t)
        if dropped:
            conn.commit()
            conn.execute("VACUUM")
            conn.commit()
    finally:
        conn.close()
    return dropped


def global_min_max_timestamps(path: Path, ts_col: str) -> tuple[int | None, int | None]:
    conn = sqlite3.connect(str(path))
    try:
        mins: list[int] = []
        maxs: list[int] = []
        for t in list_user_tables(conn, "main"):
            if is_excluded_topic_table(t):
                continue
            row = conn.execute(f"SELECT MIN({ts_col}), MAX({ts_col}) FROM {qi(t)}").fetchone()
            if row and row[0] is not None:
                mins.append(int(row[0]))
                maxs.append(int(row[1]))
        if not mins:
            return None, None
        return min(mins), max(maxs)
    finally:
        conn.close()


def write_metadata_output(
    src_metadata: Path,
    dst_metadata: Path,
    out_dat_name: str,
    min_ts: int,
    max_ts: int,
) -> None:
    shutil.copy2(src_metadata, dst_metadata)
    conn = sqlite3.connect(str(dst_metadata))
    try:
        conn.execute("DELETE FROM Files")
        conn.execute(
            "INSERT INTO Files (file_name, min_timestamp, max_timestamp) VALUES (?, ?, ?)",
            (out_dat_name, min_ts, max_ts),
        )
        conn.commit()
    finally:
        conn.close()


def run_merge_and_slice_abs(
    input_dir: Path,
    output_dir: Path,
    start_timestamp_ns: int,
    end_timestamp_ns: int,
    *,
    clip_to_localpose: bool = True,
    localpose_table: str = "LocalPoseTopic@100",
    recording_index: int = 0,
) -> MergeSliceResult:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    metadata_path = input_dir / "metadata"
    discovery_path = input_dir / "discovery"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing metadata: {metadata_path}")
    if not discovery_path.is_file():
        raise FileNotFoundError(f"missing discovery: {discovery_path}")

    t_lo = int(start_timestamp_ns)
    t_hi = int(end_timestamp_ns)
    if t_hi <= t_lo:
        raise ValueError(f"invalid window: t_lo={t_lo} t_hi={t_hi}")

    ts_col = time_column_name("source")
    logger.info("merge_slice_abs window [%s, %s]", t_lo, t_hi)

    dats = sorted_recording_dats(input_dir)
    if clip_to_localpose:
        b = localpose_bounds_in_window_dats(dats, t_lo, t_hi, ts_col, localpose_table)
        if b is not None:
            t_lo, t_hi = b
            logger.info("tightened window by %s -> [%s, %s]", localpose_table, t_lo, t_hi)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_name = default_output_dat_name(recording_index)
    merged_path = output_dir / out_name
    slice_t_lo, slice_t_hi = t_lo, t_hi

    merge_chain_filtered(dats, merged_path, ts_col, t_lo, t_hi)
    if clip_to_localpose:
        b = localpose_bounds_in_window_merged(merged_path, t_lo, t_hi, ts_col, localpose_table)
        if b is not None:
            slice_t_lo, slice_t_hi = b
            if (slice_t_lo, slice_t_hi) != (t_lo, t_hi):
                slice_dat(merged_path, slice_t_lo, slice_t_hi, ts_col)

    dropped = drop_excluded_topic_tables(merged_path)
    if dropped:
        logger.info("dropped topics: %s", dropped)

    g_min, g_max = global_min_max_timestamps(merged_path, ts_col)
    if g_min is None:
        raise RuntimeError(f"no samples in merged dat after slice [{slice_t_lo}, {slice_t_hi}]")

    write_metadata_output(metadata_path, output_dir / "metadata", out_name, g_min, g_max)
    shutil.copy2(discovery_path, output_dir / "discovery")

    return MergeSliceResult(
        merged_dat_path=merged_path,
        output_dir=output_dir,
        out_dat_name=out_name,
        min_timestamp=g_min,
        max_timestamp=g_max,
    )
