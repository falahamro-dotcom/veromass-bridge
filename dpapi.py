"""
Thin ctypes wrapper around Windows DPAPI (crypt32.dll's CryptProtectData /
CryptUnprotectData) — no pywin32 dependency needed. Seals bytes to the
current OS user: only that Windows account (on this machine) can unseal
them again, which is exactly the token-vault property the architecture doc
calls for ("Windows DPAPI token vault... CryptProtectData").

CRYPTPROTECT_UI_FORBIDDEN is always passed so this can never pop a Windows
dialog — a background CLI tool must not block on a UI prompt.
"""

import ctypes
import ctypes.wintypes as wintypes
import platform

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _require_windows():
    if platform.system() != "Windows":
        raise RuntimeError(
            "dpapi.py only works on Windows (this is a Windows desktop Bridge) — "
            f"got platform.system() == {platform.system()!r}"
        )


def protect(data: bytes) -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_blob = _blob(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def unprotect(sealed: bytes) -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_blob = _blob(sealed)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
