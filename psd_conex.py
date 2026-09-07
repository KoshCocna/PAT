"""
Newport CONEX-PSD10GE 읽기 래퍼

기존 코드들이 매 파일마다 clr.AddReference + PSD.GP(1)를 반복하던 것을
한 곳으로 모은 것. 동작은 동일하다.
"""

import os
import sys
import clr

DLL_PATH = r"C:\Windows\Microsoft.NET\assembly\GAC_64\Newport.CONEXPSD.CommandInterface\v4.0_2.0.0.3__0e6bb3450a1048fd\Newport.CONEXPSD.CommandInterface.dll"

if not os.path.exists(DLL_PATH):
    print("CONEX-PSD DLL not found:", DLL_PATH)
    sys.exit(-1)

clr.AddReference(DLL_PATH)
from CommandInterfaceConexPSD import ConexPSD  # noqa: E402


class PSD:
    """CONEX-PSD10GE. read()는 (x_mm, y_mm, power)를 돌려준다."""

    def __init__(self, port="COM6", channel=1):
        self.port = port
        self.channel = channel
        self._dev = None

    def open(self):
        self._dev = ConexPSD()
        comp_id = self._dev.OpenInstrument(self.port)
        if comp_id != 0:
            raise RuntimeError(f"CONEX-PSD 연결 실패 (port={self.port}, id={comp_id})")
        print(f"[PSD] connected on {self.port}")
        return self

    def read(self):
        """단발 읽기. 실패 시 (None, None, 0.0)."""
        try:
            result, x_mm, y_mm, power, err = self._dev.GP(self.channel)
            if result != 0:
                return None, None, 0.0
            return x_mm, y_mm, power
        except Exception as e:
            print(f"[PSD] read error: {e}")
            return None, None, 0.0

    def read_avg(self, n=20):
        """n회 평균. 캘리브레이션용 (샷노이즈 억제)."""
        xs, ys, ps = [], [], []
        for _ in range(n):
            x, y, p = self.read()
            if x is not None:
                xs.append(x)
                ys.append(y)
                ps.append(p)
        if not xs:
            return None, None, 0.0
        return sum(xs) / len(xs), sum(ys) / len(ys), sum(ps) / len(ps)

    def close(self):
        if self._dev is not None:
            try:
                self._dev.CloseInstrument()
            except Exception:
                pass
            self._dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
