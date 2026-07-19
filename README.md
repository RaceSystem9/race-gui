# 🏁 RaceSystem

> **ROS2 기반 자율주행 대회 운영 시스템**
>
> RaceSystem은 Raspberry Pi, ESP32, Windows GUI를 이용하여 자율주행 대회를 운영하기 위한 통합 플랫폼입니다.

# 🖥️ race-gui

> **대회 운영 GUI 프로그램**

`race-gui`는 Windows에서 실행되는 운영자 프로그램입니다.

운영자는 GUI를 이용하여 경기 시작, 팀 선택, 순위 확인, 장치 상태 확인 및 방송 화면을 제어합니다.

---

## 주요 기능

* 경기 시작 / 종료
* 참가팀 관리
* 실시간 기록 표시
* 순위 표시
* 장치 상태 모니터링
* OBS 방송 화면 출력
* 환경설정

---

## 개발 환경

* Windows
* Python
* PySide6 (Qt)
* WebSocket

---

## 프로젝트 구조

```text
src/
resources/
icons/
themes/
```

---

## 관련 Repository

* race-core
* race-esp32
* race-docs

---

RaceSystem Project

## Local WebSocket Simulation Test

Use the local test server when the Raspberry Pi implementation is incomplete.

1. Start server (normal ACK)

```powershell
python websocket_server.py --host 0.0.0.0 --port 8765
```

2. Start server with realistic instability simulation

```powershell
python websocket_server.py --host 0.0.0.0 --port 8765 --ack-delay-ms 120 --ack-jitter-ms 200 --ack-drop-rate 0.1 --ack-fail-rate 0.05 --disconnect-after-ack-rate 0.05
```

3. Run LED command test client (single)

```powershell
python tools/ws_led_test_client.py --host 127.0.0.1 --port 8765 --color GREEN
```

4. Run repeated reliability test

```powershell
python tools/ws_led_test_client.py --host 127.0.0.1 --port 8765 --color RED --repeat 30 --interval 0.2 --timeout 2.0
```

Notes:
- The app client sends set_traffic_light and expects ACK messages.
- ACK payload supports status=ok/fail and can be delayed, dropped, or followed by simulated disconnect.
- race-gui WebSocket endpoint can be changed with environment variables before launch:

```powershell
$env:RACE_WS_HOST = "127.0.0.1"
$env:RACE_WS_PORT = "8765"
python main.py
```
