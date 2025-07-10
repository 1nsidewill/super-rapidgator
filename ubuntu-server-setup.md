# Ubuntu 서버 설정 가이드 - Super Rapidgator

## 🚀 **우분투 서버에서 Celery 병렬 다운로드 시스템 설정**

### 1. **Redis 서버 설정**

```bash
# Redis 서버 상태 확인
sudo systemctl status redis-server

# Redis 서버 시작
sudo systemctl start redis-server

# Redis 서버 자동 시작 설정
sudo systemctl enable redis-server

# Redis 접속 테스트
redis-cli ping
# 응답: PONG
```

### 2. **프로젝트 배포**

```bash
# 프로젝트 디렉토리로 이동
cd /path/to/your/super-rapidgator

# 환경 변수 설정
cp .env.example .env
nano .env
```

**환경 변수 설정 (.env 파일):**
```env
# Rapidgator 로그인 정보
RAPIDGATOR_USERNAME=your_rapidgator_username
RAPIDGATOR_PASSWORD=your_rapidgator_password

# 다운로드 경로
DOWNLOAD_PATH=/home/user/downloads
DEBUG=false

# Redis 설정 (로컬 서버)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
# REDIS_PASSWORD=your_redis_password_if_any

# 또는 직접 Redis URL 설정
REDIS_URL=redis://localhost:6379/0

# Celery 설정
CELERY_WORKER_CONCURRENCY=4  # CPU 코어 수에 맞게 조정
CELERY_TASK_TIME_LIMIT=3600  # 1시간
CELERY_TASK_SOFT_TIME_LIMIT=3300  # 55분
```

### 3. **의존성 설치**

```bash
# Python 가상환경 설정
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 또는 uv 사용
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### 4. **Celery Worker 실행**

#### **단일 Worker 실행:**
```bash
# 기본 워커 실행
export DOWNLOAD_PATH="/home/user/downloads"
export REDIS_URL="redis://localhost:6379/0"
export RAPIDGATOR_USERNAME="your_username"
export RAPIDGATOR_PASSWORD="your_password"

cd /path/to/super-rapidgator
celery -A src.super_rapidgator.workers.celery_app worker --loglevel=info
```

#### **멀티 워커 실행 (추천):**
```bash
# 4개의 워커 프로세스로 실행 (병렬 다운로드)
celery -A src.super_rapidgator.workers.celery_app worker --loglevel=info --concurrency=4

# 또는 auto-scale 사용
celery -A src.super_rapidgator.workers.celery_app worker --loglevel=info --autoscale=8,2
```

### 5. **Celery 모니터링**

#### **Celery Flower (웹 모니터링):**
```bash
# Flower 설치
pip install flower

# Flower 실행
celery -A src.super_rapidgator.workers.celery_app flower --port=5555
```

#### **Celery 상태 확인:**
```bash
# 워커 상태 확인
celery -A src.super_rapidgator.workers.celery_app status

# 활성 태스크 확인
celery -A src.super_rapidgator.workers.celery_app inspect active

# 큐 상태 확인
celery -A src.super_rapidgator.workers.celery_app inspect reserved
```

### 6. **FastAPI 서버 실행**

```bash
# 프로덕션 모드로 실행
export DOWNLOAD_PATH="/home/user/downloads"
export REDIS_URL="redis://localhost:6379/0"
export RAPIDGATOR_USERNAME="your_username"
export RAPIDGATOR_PASSWORD="your_password"

# Uvicorn으로 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

# 또는 직접 실행
python main.py
```

### 7. **Systemd 서비스 설정 (자동 시작)**

#### **Celery Worker 서비스:**
```bash
sudo nano /etc/systemd/system/celery-worker.service
```

```ini
[Unit]
Description=Celery Worker for Super Rapidgator
After=redis-server.service

[Service]
Type=simple
User=your_user
Group=your_group
WorkingDirectory=/path/to/super-rapidgator
Environment=DOWNLOAD_PATH=/home/user/downloads
Environment=REDIS_URL=redis://10.0.0.1:6379/0
Environment=RAPIDGATOR_USERNAME=your_username
Environment=RAPIDGATOR_PASSWORD=your_password
ExecStart=/path/to/super-rapidgator/venv/bin/celery -A src.super_rapidgator.workers.celery_app worker --loglevel=info --concurrency=4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### **FastAPI 서버 서비스:**
```bash
sudo nano /etc/systemd/system/super-rapidgator.service
```

```ini
[Unit]
Description=Super Rapidgator FastAPI Server
After=network.target redis-server.service

[Service]
Type=simple
User=your_user
Group=your_group
WorkingDirectory=/path/to/super-rapidgator
Environment=DOWNLOAD_PATH=/home/user/downloads
Environment=REDIS_URL=redis://localhost:6379/0
Environment=RAPIDGATOR_USERNAME=your_username
Environment=RAPIDGATOR_PASSWORD=your_password
ExecStart=/path/to/super-rapidgator/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### **서비스 활성화:**
```bash
# 서비스 다시 로드
sudo systemctl daemon-reload

# 서비스 시작
sudo systemctl start celery-worker
sudo systemctl start super-rapidgator

# 자동 시작 설정
sudo systemctl enable celery-worker
sudo systemctl enable super-rapidgator

# 서비스 상태 확인
sudo systemctl status celery-worker
sudo systemctl status super-rapidgator
```

### 8. **방화벽 설정**

```bash
# 포트 8000 열기 (FastAPI 서버)
sudo ufw allow 8000

# 포트 5555 열기 (Flower 모니터링)
sudo ufw allow 5555

# 방화벽 상태 확인
sudo ufw status
```

### 9. **로그 확인**

```bash
# Celery 워커 로그
sudo journalctl -u celery-worker -f

# FastAPI 서버 로그
sudo journalctl -u super-rapidgator -f

# Redis 로그
sudo journalctl -u redis-server -f
```

### 10. **성능 최적화**

#### **Redis 설정 최적화:**
```bash
sudo nano /etc/redis/redis.conf
```

```conf
# 메모리 설정
maxmemory 2gb
maxmemory-policy allkeys-lru

# 성능 설정
tcp-keepalive 60
timeout 300
```

#### **Celery 설정 최적화:**
```bash
# 워커 수 조정 (CPU 코어 수 * 2)
celery -A src.super_rapidgator.workers.celery_app worker --concurrency=8

# 메모리 사용량 제한
celery -A src.super_rapidgator.workers.celery_app worker --max-memory-per-child=1000000
```

### 11. **테스트**

```bash
# API 테스트
curl -X POST "http://localhost:8000/api/download/start" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://rg.to/file/test_file_url"],
    "batch_name": "Test Batch",
    "use_celery": true
  }'

# 배치 상태 확인
curl "http://localhost:8000/api/download/batches/BATCH_ID"
```

---

## 🎯 **예상 성능**

- **동시 다운로드**: 4-8개 파일 (워커 수에 따라)
- **처리량**: 30개 창을 열던 것과 유사한 성능
- **안정성**: 서버 재시작 시에도 진행 상황 유지
- **모니터링**: 실시간 상태 추적 가능

## 📊 **모니터링 URL**

- **FastAPI 서버**: `http://your-server-ip:8000`
- **API 문서**: `http://your-server-ip:8000/docs`
- **Flower 모니터링**: `http://your-server-ip:5555`

이제 우분투 서버에서 병렬 다운로드 시스템이 완전히 구동됩니다! 🚀 