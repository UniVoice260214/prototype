# data/ — 코퍼스와 chunk_id 체계

- `raw/`: 원본 자료 (PDF/JSON)
- `raw_distractor/`: 방해물 PDF (선택, `ingest.py --with-distractors`)
- `chunks/chunks.jsonl`: 청킹 결과 — 한 줄 = 한 chunk
  (`chunk_id`, `source`, `doc_type`, `text`, `metadata`)

생성: `python src/ingest.py` (파서 규칙은 `src/ingest.py` 모듈 docstring 참조)

## chunk_id 명명 규칙

| 접두사 | doc_type | 원본 | 형식 | 예시 |
|--------|----------|------|------|------|
| `lecNN_` | lecture_slide | `I2A_LectureNN*.pdf` | `lecNN_p{시작페이지}_{끝페이지}` (같은 제목의 연속 슬라이드 병합) | `lec02_p03_06` = Lecture02의 3~6페이지 |
| `concept_` | concept_doc | `인공지능_개념_지식자료.pdf` | `concept_ch{장}_s{절순번}` | `concept_ch4_s3` = 4장의 3번째 소제목 절 |
| `glossary_` | glossary | `ai_glossary_1.json` | `glossary_{용어id}` (용어당 1 chunk) | `glossary_task_environment` |
| `tb_` | textbook | `인공지능_입문_교재.pdf` | 아래 세부 표 참조 | `tb_ch08_s4` |
| `distr_` | distractor | `raw_distractor/*.pdf` | `distr_{파일명slug}_...` (슬라이드/문서형 규칙 자동 적용) | — |

### textbook (`tb_*`) 세부

교재의 장(제N장)·절(N.M) 구조를 그대로 반영:

| 형식 | 의미 | 예시 |
|------|------|------|
| `tb_chNN_intro` | 제N장 도입부(개요 문단) | `tb_ch01_intro` |
| `tb_chNN_sM` | 제N장 M절 본문 | `tb_ch08_s4` = 8장 4절 "차원의 저주" |
| `tb_chNN_sM_2` | 절이 500토큰 초과로 overlap 분할된 2번째 조각 | `tb_ch16_s2_2` |
| `tb_chNN_summary` | 그 장의 "이 장의 요약" | `tb_ch08_summary` |
| `tb_chNN_terms` (`_2`) | 그 장의 "핵심 용어" 표 (초과 시 분할) | `tb_ch15_terms_2` |

`metadata.chapter`(예: "제8장 비지도학습과 차원 축소")와 `metadata.section_title`로
사람이 읽을 수 있는 위치 정보를 함께 보관한다.

참고: 교재 PDF 자체는 `tools/content_part1~4.py`의 16개 장 콘텐츠로
`tools/build_textbook.py`가 생성한 자체 제작 교재다
(스펙: `.omc/specs/deep-interview-ai-intro-textbook.md`).

### 접미사 공통 규칙

- `_2`, `_3` … : `MAX_SECTION_TOKENS`(500) 초과로 overlap(50토큰) 분할된 뒷조각.
  접미사 없는 id가 첫 조각.

## chunk 전문 확인

```powershell
Select-String -Path data\chunks\chunks.jsonl -Pattern '"tb_ch08_s4"' | % Line
```
