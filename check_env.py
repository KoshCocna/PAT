"""
환경 점검 — 작업용 노트북에서 가장 먼저 돌린다.

클론 직후 "무엇이 준비됐고 무엇이 빠졌는지"를 한 번에 알려준다.
하드웨어를 전혀 건드리지 않는다. --connect 를 줬을 때만 실제로 연결해 본다.

    python check_env.py              # 점검만 (안전)
    python check_env.py --connect    # 실제 연결까지 시도 (FSM 이 중앙으로 이동함)

이 스크립트만은 numpy 도 없는 상태에서 돌아가야 하므로 표준 라이브러리만 쓴다.
"""

import glob
import os
import platform
import sys

OK = "[ OK ]"
NG = "[FAIL]"
WARN = "[WARN]"

# psd_conex.py 가 참조하는 경로와 같아야 한다
DLL_PATH = (r"C:\Windows\Microsoft.NET\assembly\GAC_64"
            r"\Newport.CONEXPSD.CommandInterface"
            r"\v4.0_2.0.0.3__0e6bb3450a1048fd"
            r"\Newport.CONEXPSD.CommandInterface.dll")

problems = []
notes = []


def head(t):
    print("\n" + "=" * 68)
    print("  " + t)
    print("=" * 68)


# ----------------------------------------------------------------- 1. Python
def check_python():
    head("1. Python")
    v = sys.version_info
    bits = 64 if sys.maxsize > 2 ** 32 else 32
    print(f"  버전   : {v.major}.{v.minor}.{v.micro}  ({platform.python_implementation()})")
    print(f"  아키텍처: {bits}-bit")
    print(f"  실행경로: {sys.executable}")
    print(f"  가상환경: {'예' if sys.prefix != sys.base_prefix else '아니오 (venv 권장)'}")

    if bits != 64:
        print(f"  {NG} 32-bit Python 이다. CONEX DLL 이 GAC_64 에 있으므로 64-bit 가 필요하다.")
        problems.append("64-bit Python 으로 다시 설치할 것")
    else:
        print(f"  {OK} 64-bit")

    if (v.major, v.minor) < (3, 9):
        print(f"  {NG} 너무 낮다. 3.11 또는 3.12 권장.")
        problems.append("Python 3.11 또는 3.12 설치")
    elif (v.major, v.minor) > (3, 12):
        print(f"  {WARN} 3.{v.minor} 는 벤더 SDK(optoMDC, pythonnet)에서 검증되지 않았다.")
        print(f"         문제가 생기면 3.12 로 내려서 다시 시도할 것.")
        notes.append(f"Python 3.{v.minor} 는 벤더 SDK 미검증 — 실패 시 3.12 로")
    else:
        print(f"  {OK} 버전 적합")

    if sys.prefix == sys.base_prefix:
        notes.append("가상환경(venv) 없이 전역에 설치 중")


# ----------------------------------------------------------------- 2. 패키지
def check_packages():
    head("2. 패키지")
    required = [
        ("numpy", "수치 연산", True),
        ("matplotlib", "GUI 플롯", True),
        ("clr", "pythonnet — CONEX .NET DLL 로딩", True),
        ("optoMDC", "Optotune MR-E-3 SDK (PyPI 아님)", True),
        ("serial", "pyserial — COM 포트 조회", False),
        ("scipy", "해석용", False),
        ("zaber_motion", "3단계용", False),
    ]
    for name, why, must in required:
        try:
            m = __import__(name)
            ver = getattr(m, "__version__", "")
            print(f"  {OK} {name:<14} {ver:<10} {why}")
        except Exception as e:
            tag = NG if must else WARN
            print(f"  {tag} {name:<14} {'':<10} {why}")
            print(f"         └ {type(e).__name__}: {str(e)[:70]}")
            if must:
                if name == "optoMDC":
                    problems.append(
                        "optoMDC 설치 — optotune.com/software-download 에서 wheel 을 받아\n"
                        "         optoKummenberg 먼저, 그다음 optoMDC (MR-E-3 는 1.3.4781 이상)")
                elif name == "clr":
                    problems.append("pip install pythonnet")
                else:
                    problems.append(f"pip install {name}")


# ----------------------------------------------------------------- 3. CONEX DLL
def check_dll():
    head("3. Newport CONEX-PSD .NET 어셈블리")
    if os.path.exists(DLL_PATH):
        print(f"  {OK} 기본 경로에 있음")
        print(f"       {DLL_PATH}")
        return

    print(f"  {NG} psd_conex.py 가 보는 경로에 없다:")
    print(f"       {DLL_PATH}")

    # GAC 어디든 Newport CONEXPSD 어셈블리가 있는지 찾아본다
    pats = [
        r"C:\Windows\Microsoft.NET\assembly\GAC_64\Newport.CONEXPSD*\*\*.dll",
        r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Newport.CONEXPSD*\*\*.dll",
        r"C:\Windows\assembly\GAC_64\Newport.CONEXPSD*\*\*.dll",
    ]
    found = []
    for p in pats:
        found += glob.glob(p)

    if found:
        print(f"\n  {WARN} 다른 버전 경로에서 찾았다. psd_conex.py 의 DLL_PATH 를 아래로 바꿀 것:")
        for f in found:
            print(f"       {f}")
        problems.append("psd_conex.py 의 DLL_PATH 를 위에서 찾은 실제 경로로 수정")
    else:
        print(f"\n  GAC 어디에서도 못 찾았다. Newport CONEX-PSD 소프트웨어를 설치할 것.")
        problems.append("Newport CONEX-PSD 소프트웨어 설치 (DLL 이 GAC 에 등록된다)")


# ----------------------------------------------------------------- 4. COM 포트
def check_ports():
    head("4. COM 포트")
    try:
        from serial.tools import list_ports
    except Exception:
        print(f"  {WARN} pyserial 이 없어 포트를 나열할 수 없다.")
        print(f"         장치관리자 > 포트(COM & LPT) 에서 직접 확인할 것.")
        return

    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    if not ports:
        print(f"  {NG} COM 포트가 하나도 안 보인다. USB 연결과 드라이버를 확인할 것.")
        problems.append("장비 USB 연결 / 드라이버 확인")
        return

    for p in ports:
        print(f"  {p.device:<8} {(p.description or '')[:52]}")
        if p.hwid and p.hwid != "n/a":
            print(f"           {p.hwid[:60]}")

    print(f"\n  psd_conex.py 의 DEFAULT_PORT 를 CONEX-PSD 포트로 맞출 것 (여기 한 곳뿐이다).")
    print(f"  FSM 은 자동 탐색이라 보통 그대로 둔다 (실패 시 fsm_optotune.DEFAULT_PORT 지정).")


# ----------------------------------------------------------------- 5. 실제 연결
def try_connect():
    head("5. 실제 연결 (--connect)")
    print("  주의: FSM 이 중앙(u=0)으로 이동한다.\n")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    try:
        from psd_conex import PSD, DLL_PATH as P
        psd = PSD().open()
        x, y, p = psd.read()
        if x is None:
            print(f"  {WARN} PSD 연결은 됐으나 읽기 실패. 빔이 없거나 채널이 다를 수 있다.")
        else:
            print(f"  {OK} PSD  : ({x:+.3f}, {y:+.3f}) mm, power = {p:.2f}")
            if p < 1.0:
                print(f"         광량이 거의 0 이다. 빔이 PSD 에 안 들어오고 있다.")
        psd.close()
    except SystemExit:
        print(f"  {NG} PSD  : DLL 이 없어 psd_conex 임포트 단계에서 종료됐다.")
    except Exception as e:
        print(f"  {NG} PSD  : {type(e).__name__}: {str(e)[:70]}")
        problems.append("PSD 연결 실패 — 포트 번호와 케이블 확인")

    try:
        from fsm_optotune import OptotuneFSM
        fsm = OptotuneFSM().connect()
        print(f"  {OK} FSM  : 연결됨, u = {fsm.get_units()}")
        if fsm.Jinv is None:
            print(f"         캘리브레이션 없음 — fsm_calibrate.py 를 아직 안 돌린 상태 (정상)")
        fsm.close()
    except Exception as e:
        print(f"  {NG} FSM  : {type(e).__name__}: {str(e)[:70]}")
        problems.append("FSM 연결 실패 — USB 연결과 optoMDC 설치 확인")


# ----------------------------------------------------------------- 결과
def summary():
    head("결과")
    if notes:
        print("  참고:")
        for n in notes:
            print(f"    - {n}")
        print()

    if not problems:
        print("  막는 문제 없음. 다음 순서로 진행할 것:\n")
        print("    1) L 실측 (FSM -> BS -> PSD)")
        print("    2) python check_env.py --connect   # 아직 안 했다면")
        print("    3) python fsm_jog.py               # 조향이 보이는지 확인")
        print("    4) python fsm_calibrate.py         # J 실측")
        print("    5) python fsm_PID.py               # 폐루프 추적")
        return 0

    print(f"  해결할 것 {len(problems)} 가지:\n")
    for i, p in enumerate(problems, 1):
        print(f"    {i}. {p}")
    print("\n  전부 해결한 뒤 이 스크립트를 다시 돌릴 것.")
    return 1


def main():
    print("=" * 68)
    print("  PAT 환경 점검")
    print("=" * 68)
    check_python()
    check_packages()
    check_dll()
    check_ports()
    if "--connect" in sys.argv:
        try_connect()
    else:
        head("5. 실제 연결")
        print("  건너뜀. 장비를 연결한 뒤 --connect 를 붙여 다시 돌릴 것.")
    return summary()


if __name__ == "__main__":
    sys.exit(main())
