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
