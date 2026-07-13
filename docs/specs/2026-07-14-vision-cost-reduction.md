# vision 비용 절감 설계 (2026-07-14)

## 배경
- 실측(2026-07): API 비용의 약 26%가 `vision`(차트·캡처 이미지 → Claude 한국어 설명).
- 완전 동일 이미지는 이미 `image_cache`(sha1 PK)로 재호출을 막고 있으나, **재인코딩·재압축·리사이즈된 동일 차트**는 sha1이 달라 매번 다시 호출된다(같은 차트가 여러 채널에 재업로드되는 경우 흔함).
- 또한 텔레그램 원본 이미지는 1280px+가 많아, vision 입력 이미지 토큰이 필요 이상으로 크다.

## 목표
호출·토큰 회피로 vision 비용을 줄이되, 3줄 차트 요약 품질은 유지한다. 두 레버:

### 2a. 다운샘플 (기본 활성)
- API 전송 전 이미지를 장변 `_MAX_IMAGE_EDGE`(=1024)로 축소하고 JPEG(q=`_JPEG_QUALITY`=85)로 재인코딩.
- 이미지 토큰은 해상도에 비례하므로 큰 이미지에서 입력 토큰이 직접 감소.
- 3줄 요약(숫자·종목명 추출)에는 1024px면 충분. 실패(디코드 불가) 시 원본 그대로 전송(graceful degrade).
- **sha1 캐시 키는 원본 바이트 기준 유지** — 다운샘플은 전송용일 뿐 캐시 정합성에 영향 없음.

### 2b. 유사이미지(perceptual hash) 캐시 (기본 shadow)
- 각 이미지의 `phash`(64bit)를 `image_cache.phash`에 저장.
- sha1 miss 시, 최근 phash들과 Hamming 거리 비교 → `image_phash_max_distance`(기본 4) 이하면 "같은 이미지 재인코딩"으로 보고 기존 설명 재사용(호출 회피).
- **오탐 위험**: 서로 다른 차트가 같은 템플릿(축·레이아웃)을 쓰면 phash가 가까울 수 있음. 재인코딩된 동일 이미지는 보통 0~4비트, 다른 차트는 10비트+로 갈리므로 임계값 4를 보수적 기본값으로.

## 검증 게이트 (핵심 — 오프라인 코퍼스 부재 대응)
실제 이미지 코퍼스가 없어 배포 전 오프라인 검증이 불가하므로, `recent_dedup`의 "제거 건 사후 감사 로그" 방식을 채택:
- **기본은 shadow 모드**(`enable_image_phash_cache=False`): phash를 계산·저장하고, 거리 이하인 후보가 있으면 `[vision] phash 유사(shadow, 호출유지) dist=.. | 설명일부`를 INFO 로그로 남기되 **실제 호출은 유지**한다.
- 며칠 Actions 로그로 "합쳐질 뻔한" 쌍을 리뷰해 오탐(다른 차트 매칭)이 없음을 확인한 뒤, `ENABLE_IMAGE_PHASH_CACHE=true`로 켜면 그때부터 실제로 호출을 건너뛴다(`[vision] phash 재사용 dist=..`).
- 임계값도 `IMAGE_PHASH_MAX_DISTANCE` env로 조정 가능.

## 구성 요소
- `requirements.txt`: `pillow`, `imagehash` 추가.
- `config.py`: `enable_image_phash_cache: bool = False`, `image_phash_max_distance: int = 4`.
- `state_repo.py`: `image_cache`에 `phash` 컬럼(idempotent ALTER 마이그레이션), `set_image_cache(..., phash)`, `get_image_phashes(limit)`.
- `vision.py`: `_prepare`(1회 디코드 → 전송바이트·media_type·phash), `_downsample`, `_nearest_phash`(순수 함수, 단위 테스트 가능), shadow/enable 분기.
- `main.py`: `VisionService`에 설정 주입.

## 되돌리기
2a·2b 모두 문제 시 커밋 revert. 2b는 env로 즉시 shadow 복귀 가능.

## 범위 밖 (YAGNI)
- 이미지 내용 기반 필터(vision을 돌려야 알 수 있음 → 취지에 반함).
- phash 인덱싱 구조(수백 행 스캔은 로컬 수 ms라 불필요).
