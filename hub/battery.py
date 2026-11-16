"""跨平台电池读数。

Windows 用原生 GetSystemPowerStatus，能区分三件事：
  ac       = 是否插着电源适配器
  charging = 是否正在充电（已充满时为 False）
  pct      = 电量百分比

其它平台回退到 psutil（只能给出"插电与否"，把 ac 和 charging 视作同一件事）。

返回 {"pct": int|None, "charging": bool|None, "ac": bool|None}
"""
import ctypes
import sys


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def read_windows():
    s = _SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    pct = None if s.BatteryLifePercent == 255 else int(s.BatteryLifePercent)
    ac = s.ACLineStatus == 1
    charging = bool(s.BatteryFlag & 0x08)   # bit3 = 正在充电
    return {"pct": pct, "charging": charging, "ac": ac}


def read_psutil():
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return {"pct": None, "charging": None, "ac": None}
        plugged = bool(b.power_plugged)
        return {"pct": int(round(b.percent)), "charging": plugged, "ac": plugged}
    except Exception:
        return {"pct": None, "charging": None, "ac": None}


def read():
    if sys.platform == "win32":
        try:
            r = read_windows()
            if r and r["pct"] is not None:
                return r
        except Exception:
            pass
    return read_psutil()


if __name__ == "__main__":
    print(read())
