"""FSM 포트 찾기 - 빠른 타임아웃으로 각 포트 시도"""
import sys
import io
import threading

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("FSM (Optotune MR-E-3) 포트 탐색")
print("=" * 60)
print("\n각 포트를 3초씩 시도합니다...\n")

import optoMDC

# PSD가 사용 중인 COM6은 제외
test_ports = ["COM5", "COM7", "COM3"]

def try_connect(port, result_dict):
    """스레드에서 연결 시도"""
    try:
        mre = optoMDC.connectmre3(port=port)
        result_dict[port] = "SUCCESS"
        if hasattr(mre, 'disconnect'):
            mre.disconnect()
        else:
            mre.close()
    except Exception as e:
        result_dict[port] = f"FAIL: {type(e).__name__}"

for port in test_ports:
    print(f"[{port}] 시도 중...", end=" ", flush=True)

    result = {}
    thread = threading.Thread(target=try_connect, args=(port, result))
    thread.daemon = True
    thread.start()
    thread.join(timeout=3.0)  # 3초 타임아웃

    if thread.is_alive():
        print("✗ 타임아웃 (3초)")
    elif port in result:
        if "SUCCESS" in result[port]:
            print(f"✓ 성공!")
            print(f"\n{'='*60}")
            print(f"FSM은 {port}에 연결되어 있습니다!")
            print(f"{'='*60}")
            print(f"\nfsm_optotune.py의 DEFAULT_PORT를 '{port}'로 설정하세요.")
            sys.exit(0)
        else:
            print(f"✗ {result[port]}")
    else:
        print("✗ 응답 없음")

print("\n" + "=" * 60)
print("모든 포트에서 FSM을 찾지 못했습니다.")
print("=" * 60)
print("\n가능한 원인:")
print("1. FSM 전원이 꺼져 있음")
print("2. USB 케이블 연결 불량")
print("3. 드라이버 문제")
print("4. FSM이 다른 프로그램에서 사용 중")
