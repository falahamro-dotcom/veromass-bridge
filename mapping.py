"""
Maps a veromass-aligner `aligned_features.xlsx` workbook into the commit
body shapes expected by moleculeid-api's POST /api/jobs/{job_id}/commit
(see moleculeid-api/workbench_routes.py: FeatureInput, JobCommit).

Targeted jobs  -> {"features": [{"mz", "rt", "intensity", "fragments"}, ...]}
Untargeted jobs -> {"feature_matrix": {"<feature>": {"<sample>": <intensity>}}}

Pure functions, no network/auth here — easy to unit-test against a real
workbook produced by veromass-aligner.
"""

import openpyxl


def _read_sheet_as_dicts(ws):
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    return [dict(zip(header, row)) for row in rows]


def build_targeted_features(xlsx_path):
    """Read the Features sheet -> list of FeatureInput-shaped dicts.

    intensity uses Base.Peak (the representative peak height for the
    feature); fragments is passed through as-is since MS2.Fragments is
    already in the server's expected "mz(pct%); mz(pct%)" string format.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Features"]
    out = []
    for row in _read_sheet_as_dicts(ws):
        mz = row.get("m.z")
        rt = row.get("RT")
        if mz is None or rt is None:
            continue
        out.append({
            "mz": float(mz),
            "rt": float(rt),
            "intensity": float(row.get("Base.Peak") or 0.0),
            "fragments": row.get("MS2.Fragments") or None,
        })
    return out


def build_untargeted_feature_matrix(xlsx_path):
    """Read the Intensities sheet -> {feature: {sample: intensity}}."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Intensities"]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    feature_col, sample_cols = header[0], header[1:]

    matrix = {}
    for row in rows:
        row = dict(zip(header, row))
        feature = row.get(feature_col)
        if feature is None:
            continue
        matrix[str(feature)] = {
            sample: float(row[sample]) if row.get(sample) is not None else 0.0
            for sample in sample_cols
        }
    return matrix


def build_commit_payload(xlsx_path, mode):
    """mode: "targeted" or "untargeted" -> the mode-specific body fields
    (package_uuid is added by the caller, not here)."""
    if mode == "targeted":
        return {"features": build_targeted_features(xlsx_path)}
    if mode == "untargeted":
        return {"feature_matrix": build_untargeted_feature_matrix(xlsx_path)}
    raise ValueError(f"Unknown job mode: {mode!r}")
