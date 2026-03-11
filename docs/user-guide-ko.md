# RuView 사용 설명서 (한국어)

> **English version:** [user-guide.md](user-guide.md)

이 문서는 **집에 있는 공유기(라우터)**에서 RuView를 설치하고 사용하는 방법을 단계별로 설명합니다.

---

## 목차

1. [RuView가 뭔가요?](#ruview가-뭔가요)
2. [필요한 것들](#필요한-것들)
3. [소프트웨어 설치 (aggregator 실행)](#1단계--소프트웨어-설치-aggregator-실행)
4. [내 컴퓨터 IP 주소 확인](#2단계--내-컴퓨터-ip-주소-확인)
5. [ESP32 노드 설정 (프로비저닝)](#3단계--esp32-노드-설정-프로비저닝)
6. [자동 IP 탐색 (더 쉬운 방법)](#자동-ip-탐색-더-쉬운-방법)
7. [주변 WiFi 목록 확인](#주변-wifi-목록-확인)
8. [잘 되는지 확인하기](#잘-되는지-확인하기)
9. [자주 묻는 질문 (FAQ)](#자주-묻는-질문-faq)
10. [문제 해결](#문제-해결)

---

## RuView가 뭔가요?

RuView는 **WiFi 신호(CSI)**를 이용해 카메라 없이 사람의 위치, 자세, 호흡수, 심박수를 감지하는 시스템입니다.

- 카메라가 필요 없습니다 — 사생활 침해 없이 감지
- 벽을 통해서도 동작
- ESP32-S3 보드(개당 약 8~10달러) 1~6개와 집에 있는 공유기만 있으면 됩니다

---

## 필요한 것들

| 항목 | 설명 | 비용 |
|------|------|------|
| **ESP32-S3 개발 보드** 1~6개 | WiFi CSI 캡처 장치 | 개당 약 8,000~12,000원 |
| **집에 있는 공유기** | 기존 WiFi 그대로 사용 | 추가 비용 없음 |
| **노트북 / 데스크탑** | sensing server(aggregator) 실행 | 기존 컴퓨터 그대로 사용 |
| **USB 케이블** (USB-C 또는 Micro-USB) | ESP32 설정 시 연결용 | 보통 포함 |
| **Python 3.10+** | 프로비저닝 스크립트 실행용 | 무료 |
| **Docker** (권장) | sensing server 실행용 | 무료 |

> 💡 ESP32 구매처: 알리익스프레스, 쿠팡, 네이버쇼핑에서 "ESP32-S3 개발 보드"로 검색하세요.

---

## 1단계 — 소프트웨어 설치 (aggregator 실행)

**aggregator**는 ESP32 노드로부터 WiFi 신호 데이터를 받아서 분석하는 프로그램입니다. ESP32 노드를 켜기 **전에** 먼저 실행해야 합니다.

### 방법 A: Docker (가장 쉬움)

Docker가 설치되어 있다면 이 명령어 하나로 실행됩니다:

```bash
docker run -p 3000:3000 -p 3001:3001 -p 5005:5005/udp \
  -e CSI_SOURCE=esp32 \
  ruvnet/wifi-densepose:latest
```

실행 후 브라우저에서 `http://localhost:3000` 을 열어서 화면이 뜨는지 확인하세요.

### 방법 B: 소스 빌드 (Rust)

```bash
git clone https://github.com/ruvnet/RuView.git
cd RuView/rust-port/wifi-densepose-rs
cargo build --release

./target/release/sensing-server \
  --source esp32 --udp-port 5005 --http-port 3000 --ws-port 3001
```

---

## 2단계 — 내 컴퓨터 IP 주소 확인

ESP32 노드가 공유기에 연결된 후, sensing server가 실행 중인 컴퓨터로 데이터를 보내야 합니다. 이를 위해 **내 컴퓨터의 로컬 IP 주소**를 알아야 합니다.

### Windows

1. `시작` 버튼 클릭 → `cmd` 또는 `명령 프롬프트` 실행
2. 아래 명령어 입력:

```
ipconfig
```

3. `무선 LAN 어댑터 Wi-Fi:` 또는 `Wireless LAN adapter Wi-Fi:` 항목에서 **IPv4 주소** 확인

예시:
```
무선 LAN 어댑터 Wi-Fi:
   IPv4 주소 . . . . . . : 192.168.0.15   ← 이 숫자를 메모
```

### macOS

터미널을 열고:

```bash
ipconfig getifaddr en0
```

예시 출력: `192.168.0.15`

### Linux

터미널을 열고:

```bash
ip route get 1 | awk '{print $7; exit}'
```

예시 출력: `192.168.0.15`

> 📝 이 IP 주소를 메모해 두세요. 3단계에서 `--target-ip` 옵션에 사용합니다.

> ⚠️ **IP가 자꾸 바뀐다면:** 공유기 설정에서 컴퓨터의 MAC 주소에 고정 IP(DHCP 예약)를 설정하거나, [자동 IP 탐색](#자동-ip-탐색-더-쉬운-방법) 기능을 사용하세요.

---

## 3단계 — ESP32 노드 설정 (프로비저닝)

이 단계에서는 ESP32 보드에 **공유기 이름(SSID), 비밀번호, aggregator IP 주소**를 저장합니다. 한 번 설정하면 이후에는 USB 없이 WiFi로 자동 연결됩니다.

### 먼저 esptool 설치

```bash
pip install esptool
```

### 펌웨어 굽기 (아직 안 했다면)

[릴리스 페이지](https://github.com/ruvnet/RuView/releases)에서 최신 펌웨어 파일 3개를 다운로드하세요:
- `bootloader.bin`
- `partition-table.bin`
- `esp32-csi-node.bin`

그 다음 아래 명령어로 ESP32에 굽습니다 (`COM7`은 여러분의 포트로 바꾸세요):

**Windows:**
```bash
python -m esptool --chip esp32s3 --port COM7 --baud 460800 \
  write-flash --flash-mode dio --flash-size 4MB \
  0x0 bootloader.bin 0x8000 partition-table.bin 0x10000 esp32-csi-node.bin
```

**Linux / macOS:**
```bash
python -m esptool --chip esp32s3 --port /dev/ttyUSB0 --baud 460800 \
  write-flash --flash-mode dio --flash-size 4MB \
  0x0 bootloader.bin 0x8000 partition-table.bin 0x10000 esp32-csi-node.bin
```

> 포트 확인 방법:
> - Windows: 장치 관리자 → 포트(COM & LPT)
> - Linux: `ls /dev/ttyUSB*` 또는 `ls /dev/ttyACM*`
> - macOS: `ls /dev/cu.usb*`

### WiFi 정보 입력 (프로비저닝)

이제 공유기 정보를 ESP32에 저장합니다:

**Windows (COM7 포트 예시):**
```bash
python firmware/esp32-csi-node/provision.py \
  --port COM7 \
  --ssid "공유기이름" \
  --password "WiFi비밀번호" \
  --target-ip 192.168.0.15
```

**Linux / macOS (/dev/ttyUSB0 포트 예시):**
```bash
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB0 \
  --ssid "공유기이름" \
  --password "WiFi비밀번호" \
  --target-ip 192.168.0.15
```

- `공유기이름` → 공유기의 WiFi SSID (예: `iptime_1234`, `KT_GiGA_5G_Wave2_1234` 등)
- `WiFi비밀번호` → WiFi 비밀번호
- `192.168.0.15` → 2단계에서 메모한 내 컴퓨터 IP

성공 시 출력 예시:
```
Building NVS configuration:
  WiFi SSID:     공유기이름
  WiFi Password: ****
  Target IP:     192.168.0.15
Flashing NVS partition (24576 bytes) to /dev/ttyUSB0...
NVS provisioning complete!
```

### 노드 여러 개 설정 (3개 예시)

```bash
# 노드 1
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB0 \
  --ssid "공유기이름" --password "WiFi비밀번호" \
  --target-ip 192.168.0.15

# 노드 2
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB1 \
  --ssid "공유기이름" --password "WiFi비밀번호" \
  --target-ip 192.168.0.15

# 노드 3
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB2 \
  --ssid "공유기이름" --password "WiFi비밀번호" \
  --target-ip 192.168.0.15
```

설정이 끝나면 USB를 뽑고 방 곳곳에 배치하세요. 몇 초 안에 sensing server가 데이터를 받기 시작합니다.

---

## 자동 IP 탐색 (더 쉬운 방법)

IP 주소를 직접 찾기 귀찮다면 `--auto-discover` 옵션을 사용하세요. 스크립트가 자동으로 같은 공유기에 연결된 aggregator를 찾아냅니다.

```bash
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB0 \
  --ssid "공유기이름" \
  --password "WiFi비밀번호" \
  --auto-discover
```

출력 예시:
```
Searching for aggregator on UDP broadcast port 5005...
Aggregator found at 192.168.0.15
Building NVS configuration:
  WiFi SSID:     공유기이름
  WiFi Password: ****
  Target IP:     192.168.0.15
Flashing NVS partition (24576 bytes) to /dev/ttyUSB0...
NVS provisioning complete!
```

> ⚠️ 자동 탐색이 동작하려면 sensing server(Docker 또는 소스)가 **먼저 실행 중**이어야 합니다.

---

## 주변 WiFi 목록 확인

내 공유기 이름(SSID)이 정확히 어떻게 쓰여 있는지 모르면 아래 명령어로 주변 WiFi 목록을 확인하세요:

```bash
python firmware/esp32-csi-node/provision.py --port /dev/ttyUSB0 --scan-networks
```

출력 예시:
```
Scanning for visible WiFi networks...
Found 3 network(s):
  • iptime_1234
  • KT_GiGA_5G_Wave2_ABCD
  • olleh_WiFi_Guest
```

목록에서 내 공유기 이름을 찾아 `--ssid` 옵션에 그대로 입력하세요.

---

## 잘 되는지 확인하기

1. sensing server가 실행 중인 상태에서 브라우저로 `http://localhost:3000` 에 접속
2. ESP32 노드에 전원 연결 (USB 전원 어댑터 또는 보조배터리)
3. 화면에 **"Presence detected"** 또는 포즈 데이터가 나타나면 성공입니다

---

## 자주 묻는 질문 (FAQ)

**Q: 기존 공유기를 교체하거나 새로 설치해야 하나요?**
아니요. 집에서 쓰고 있는 공유기를 그대로 사용합니다. ESP32 노드가 핸드폰처럼 WiFi에 연결됩니다.

**Q: 공유기에 포트포워딩이나 특별한 설정이 필요한가요?**
아닙니다. 모든 통신이 같은 공유기 안의 로컬 네트워크(LAN)에서만 이루어집니다. 공유기 설정 변경이 필요 없습니다.

**Q: ESP32 노드가 공유기에 연결된 것을 어떻게 확인하나요?**
공유기 관리 페이지(보통 `192.168.0.1` 또는 `192.168.1.1`)에서 연결된 기기 목록을 확인하면 `esp32-csi-node` 또는 비슷한 이름으로 나타납니다.

**Q: 컴퓨터 IP가 바뀌면 다시 프로비저닝해야 하나요?**
바뀌면 다시 해야 합니다. 이를 방지하려면:
- 공유기 관리 페이지에서 DHCP 고정 할당(IP 예약) 설정
- 또는 매번 `--auto-discover` 옵션 사용

**Q: 2.4GHz와 5GHz 공유기 중 어떤 걸 써야 하나요?**
**2.4GHz**를 사용하세요. ESP32-S3는 2.4GHz WiFi만 지원합니다. 공유기가 5GHz 전용이라면 2.4GHz 밴드를 활성화하거나 별도 2.4GHz 공유기가 필요합니다.

**Q: WiFi 비밀번호에 한글이 있어도 되나요?**
가능하면 영문+숫자 비밀번호를 사용하는 것을 권장합니다. 특수문자나 한글이 포함된 비밀번호는 인코딩 문제가 발생할 수 있습니다.

**Q: 카메라 없이 정말로 사람을 감지할 수 있나요?**
네. WiFi 전파(Channel State Information, CSI)가 사람 몸에 반사되는 패턴을 분석합니다. 17개 관절 포즈 추정, 호흡수(6-30 BPM), 심박수(40-120 BPM), 낙상 감지 등이 가능합니다.

---

## 문제 해결

### "No such file or directory: /dev/ttyUSB0"

Linux에서 ESP32를 인식하지 못하는 경우입니다. 아래를 확인하세요:

```bash
# 연결된 USB 시리얼 장치 확인
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# 권한 부여 (재로그인 필요)
sudo usermod -a -G dialout $USER
```

### "Access is denied" (Windows)

다른 프로그램(Arduino IDE 등)이 같은 COM 포트를 사용 중입니다. 해당 프로그램을 닫고 다시 시도하세요.

### 데이터가 수신되지 않음

1. sensing server가 실행 중인지 확인
2. `--target-ip`에 입력한 IP가 현재 컴퓨터 IP와 일치하는지 확인
3. Docker 사용 시 `-p 5005:5005/udp` 옵션이 있는지 확인
4. Windows 방화벽에서 UDP 5005 포트를 허용했는지 확인:
   - `Windows 방화벽` → `고급 설정` → `인바운드 규칙` → `새 규칙` → `포트 5005 UDP 허용`

### 공유기 이름(SSID)에 한글이 포함된 경우

```bash
# 한글 SSID는 따옴표로 묶어서 입력
python firmware/esp32-csi-node/provision.py \
  --port /dev/ttyUSB0 \
  --ssid "내공유기이름" \
  --password "비밀번호" \
  --target-ip 192.168.0.15
```

---

## 요약: 딱 3단계

```
1. Docker 또는 소스로 sensing server 실행
   → docker run -p 3000:3000 -p 3001:3001 -p 5005:5005/udp -e CSI_SOURCE=esp32 ruvnet/wifi-densepose:latest

2. 내 컴퓨터 IP 확인
   → ipconfig (Windows) / ip route get 1 (Linux) / ipconfig getifaddr en0 (macOS)

3. ESP32 노드에 WiFi 정보 입력
   → python firmware/esp32-csi-node/provision.py --port COM7 --ssid "공유기이름" --password "비밀번호" --target-ip <내IP>
```

브라우저에서 `http://localhost:3000` 을 열면 실시간 데이터를 볼 수 있습니다.

---

> 영어 전체 문서: [user-guide.md](user-guide.md)
