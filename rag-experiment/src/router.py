"""RAG Router — 전공별 rule trigger + 질의 정규화 + score gate.

파이프라인 위치 (prototype/ai-worker의 RagClient 구현부에 해당):
  STT 문장 → route(): 음차 치환 + 필러 제거 + 용어 매칭 → useRag/query/reason
           → (트리거 시) 임베딩 검색 → apply_gate(): top-1 < 임계값이면 OFF

라우터는 전공마다 하나씩 둔다. 세션의 과목이 전공을 결정하므로, 워커는
`RagRouter(major="bme")`처럼 전공을 지정해 생성한 뒤 그 전공 인덱스로만 검색한다.
전공별로 어휘 사전, 음차 사전, score 임계값이 모두 다르다.

산출 스키마 (RouteDecision.to_json):
  {"useRag": true, "query": "...", "reason": ["GLOSSARY_TERM", "LECTURE_CONCEPT"],
   "major": "ai", "index": "major_ai"}

어휘 사전(lexicon) 소스:
  - GLOSSARY_TERM : 전공 원본 폴더의 glossary JSON (있는 전공만)
  - LECTURE_CONCEPT: tools/ 의 교재 콘텐츠 파일에 담긴 장별 key_terms
  - TRANSLITERATIONS: glossary·key_terms가 못 덮는 음차 보충 (평가 실패 사례 기반)

ai-worker 포팅 시에는 export_lexicon()으로 JSON을 떨궈 tools/ 의존 없이 로드한다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    DATA_RAW_AI_DIR,
    DATA_RAW_BME_DIR,
    DATA_RAW_HSS_DIR,
    ROOT,
)

# ── 전공별 음차 사전 ───────────────────────────────────────────────────
# 음차 → 코퍼스 표기 보충 사전 (glossary aliases에 없는 것만).

# AI: eval/_miss_analysis_textbook_hard.txt 의 실패 사례 기반.
AI_TRANSLITERATIONS: dict[str, str] = {
    "에이치엔에스더블유": "HNSW",
    "케이 민즈": "K-평균 군집화",
    "케이민즈": "K-평균 군집화",
    "케이 평균": "K-평균",
    "트랜스퍼 러닝": "전이학습",
    "트랜스퍼러닝": "전이학습",
    "하이어라키컬 클러스터링": "계층적 군집",
    "엘에스티엠": "LSTM",
    "지알유": "GRU",
    "알오씨": "ROC",
    "에이유씨": "AUC",
    "엠에이이": "MAE",
    "알엠에스이": "RMSE",
    "엘원": "L1",
    "엘투": "L2",
    "데이터 리키지": "데이터 누수",
    "데이터 리케이지": "데이터 누수",
    "어그멘테이션": "데이터 증강",
    "백프로파게이션": "역전파",
    "포워드 체이닝": "전방향 추론",
    "백워드 체이닝": "후방향 추론",
    "배리언스": "분산",
    "피이에이에스": "PEAS",
    "스케일링 로": "스케일링 법칙",
    "덴스 검색": "밀집 검색",
    "스파스 검색": "희소 검색",
    "에이스타": "A* 탐색",
    "케이엔엔": "KNN",
    "에스브이엠": "SVM",
    "피시에이": "PCA",
    "챙킹": "청킹",
    "엘보 방법": "엘보우 방법",
    "라그": "RAG",
    "알에이지": "RAG",
}

# 인문사회: 약어와 외래어가 상대적으로 적어 사전이 작다.
HSS_TRANSLITERATIONS: dict[str, str] = {
    "지디피": "GDP",
    "지엔피": "GNP",
    "씨피아이": "CPI",
    "에이치디아이": "HDI",
    "케이디씨": "KDC",
    "디디씨": "DDC",
    "에프지아이": "FGI",
    "아이알비": "IRB",
    "알씨티": "RCT",
    "에스이에스": "SES",
    "피 값": "p값",
    "피값": "p값",
    "제트 점수": "z점수",
    "제트점수": "z점수",
    "엔아이피티": "NIPT",
    "비씨아이": "BCI",
    "에이치엘에이": "HLA",
}

# 바이오의생명공학: 약어 음차가 압도적으로 많아 사전이 가장 크다.
# eval/results_bme.md 의 stt_noise 실패 사례를 그대로 반영했다.
BME_TRANSLITERATIONS: dict[str, str] = {
    # 핵산·중심원리
    "디엔에이": "DNA",
    "알엔에이": "RNA",
    "엠아르엔에이": "mRNA",
    "엠알엔에이": "mRNA",
    "티알엔에이": "tRNA",
    "알알엔에이": "rRNA",
    "씨디엔에이": "cDNA",
    "에스엔피": "SNP",
    "엔지에스": "NGS",
    # 실험기법
    "피시알": "PCR",
    "피씨알": "PCR",
    "알티 피시알": "RT-PCR",
    "알티피시알": "RT-PCR",
    "큐피시알": "qPCR",
    "엘라이자": "ELISA",
    "엘리사": "ELISA",
    "웨스턴 블랏": "웨스턴 블롯",
    "서던 블랏": "서던 블롯",
    "노던 블랏": "노던 블롯",
    "에스디에스 페이지": "SDS-PAGE",
    "에스디에스페이지": "SDS-PAGE",
    "지에프피": "GFP",
    "에스이엠": "SEM",
    "티이엠": "TEM",
    "팩스": "FACS",
    "유세포 분석": "유세포분석",
    # 유전공학
    "크리스퍼": "CRISPR",
    "캐스나인": "Cas9",
    "크리스퍼 캐스나인": "CRISPR-Cas9",
    "가이드 알엔에이": "가이드 RNA",
    "지알엔에이": "gRNA",
    "엔에이치이제이": "NHEJ",
    "에이치디알": "HDR",
    "피에이엠": "PAM",
    "엠씨에스": "MCS",
    "히스 태그": "His-태그",
    "히스태그": "His-태그",
    "아이피티지": "IPTG",
    "에이에이브이": "AAV",
    # 세포·생화학
    "에이티피": "ATP",
    "에이디피": "ADP",
    "엔에이디에이치": "NADH",
    "지피시알": "GPCR",
    "알티케이": "RTK",
    "씨디케이": "CDK",
    "피오십삼": "p53",
    "피 오십삼": "p53",
    "아폽토시스": "세포자멸사",
    "아포토시스": "세포자멸사",
    "네크로시스": "세포괴사",
    "티씨에이 회로": "TCA 회로",
    "브이맥스": "Vmax",
    "케이엠": "Km",
    "케이캣": "kcat",
    # 면역
    "엠에이치씨": "MHC",
    "에이치엘에이": "HLA",
    "아이지지": "IgG",
    "아이지엠": "IgM",
    "아이지에이": "IgA",
    "아이지이": "IgE",
    "씨디사": "CD4",
    "씨디팔": "CD8",
    "티세포": "T세포",
    "비세포": "B세포",
    "카티": "CAR-T",
    "카티세포": "CAR-T 세포",
    "피디원": "PD-1",
    # 공정·의약품
    "씨에이치오": "CHO",
    "케이엘에이": "kLa",
    "에프비에스": "FBS",
    "지엠피": "GMP",
    "지엘피": "GLP",
    "지씨피": "GCP",
    "큐비디": "QbD",
    "에이디씨": "ADC",
    "피케이": "PK",
    "피디": "PD",
    "에이디엠이": "ADME",
    "아이엔디": "IND",
    "에프디에이": "FDA",
    "이엠에이": "EMA",
    "아이피에스씨": "iPSC",
    "이에스씨": "ESC",
    # 의공학
    "이씨지": "ECG",
    "이이지": "EEG",
    "이엠지": "EMG",
    "엠아르아이": "MRI",
    "엠알아이": "MRI",
    "에프엠아르아이": "fMRI",
    "씨티": "CT",
    "피이티": "PET",
    "에크모": "ECMO",
    "씨엠아르아르": "CMRR",
    "에이디씨 변환": "ADC 변환",
    "에일리어싱": "에일리어싱",
    "비씨아이": "BCI",
    "에스에이엠디": "SaMD",
    "디디에스": "DDS",
    "엘엔피": "LNP",
    "피엘지에이": "PLGA",
}

# 교재에는 있으나 glossary·key_terms에 빠진 개념 패턴 보충 (LECTURE_CONCEPT).
AI_SUPPLEMENTS: list[str] = [
    "ROC 곡선", "ROC", "AUC",
    "전방향 추론", "후방향 추론",
    "데이터 누수", "엘보우 방법", "HNSW", "IVF",
    "스케일링 법칙", "밀집 검색", "희소 검색", "하이브리드 검색",
    "리랭킹", "청킹", "온톨로지", "명제 논리", "술어 논리", "명제논리", "술어논리",
]

HSS_SUPPLEMENTS: list[str] = [
    # 강의에서 자주 쓰이나 용어표에는 단독으로 없는 기본 개념어
    "양적 연구", "질적 연구", "혼합연구", "상관관계", "인과관계", "교란변수",
    "통계적 유의성", "유의수준", "표본", "모집단", "설문조사", "실험",
    "미시경제학", "거시경제학", "균형가격", "수요", "공급", "탄력성",
    "중앙은행", "통화정책", "재정정책", "인플레이션", "실업",
    "선거제도", "정당", "민주주의", "권력", "권위", "국가",
    "밀그램", "애쉬", "짐바르도", "피아제", "비고츠키", "프로이트",
    "뒤르켐", "마르크스", "베버", "부르디외", "고프먼", "롤스", "칸트",
    "소쉬르", "촘스키", "랑케", "보아스", "말리노프스키", "랑가나단",
    "도서관", "분류", "십진분류법", "목록", "정보검색", "정보 리터러시",
    "사회학적 상상력", "사회적 사실", "문화자본", "헤게모니",
    "무지의 베일", "차등 원칙", "정언명령", "반증 가능성",
    "기본적 귀인 오류", "인지부조화", "방관자 효과",
    "기회비용", "매몰비용", "시장실패", "외부효과", "공공재",
    "권력분립", "입헌주의", "죄형법정주의", "적법절차",
    "문화상대주의", "자민족중심주의", "참여관찰", "민족지",
    "사료 비판", "1차 사료", "2차 사료",
    "훈민정음", "향가", "시조", "가사", "판소리",
    "재현율", "정밀도", "역색인", "메타데이터", "전거 통제",
    # 국어학(제17·18장) 보충 — 교재 key_terms가 '음운론/형태론/통사론'처럼
    # 묶음으로만 갖고 있어 강의에서 실제로 쓰이는 하위 개념이 전부 빠져 있었다.
    # KOCW 국어학개론(한국외대) 차시 대조에서 확인된 미트리거 어휘.
    "언어학", "국어학", "자연언어", "언어 유형론", "유형론",
    "자의성", "분절성", "언어의 특성",
    # 음성·음운
    "말소리", "음성학", "조음", "조음위치", "조음 위치", "조음방법", "조음 방법",
    "자음", "모음", "단모음", "이중모음", "초분절음", "운소", "억양", "성조",
    "음소", "변이음", "음절", "음절 구조", "음운현상", "음운 현상",
    "구개음화", "비음화", "유음화", "된소리되기", "두음법칙", "모음조화",
    # 형태
    "형태소", "이형태", "변이형태", "어근", "접사", "접두사", "접미사",
    "파생어", "합성어", "단일어", "파생접사", "굴절접사",
    "품사", "체언", "용언", "어간", "선어말어미", "종결어미", "연결어미",
    "격조사", "보조사", "주격조사", "목적격조사",
    # 통사
    "문장성분", "문장 성분", "서술어", "목적어", "관형어", "부사어",
    "홑문장", "겹문장", "안은문장", "이어진문장", "문형",
    "문법범주", "문법 범주", "시제", "서법", "사동", "피동",
    "사동법", "피동법", "부정법",
    # 의미
    "유의어", "반의어", "상하위어", "다의어", "동음이의어",
    "의미 관계", "의미관계", "의미 변화",
    # 국어사·어문규범
    "국어사", "고대국어", "중세국어", "근대국어", "이두", "향찰", "구결",
    "한글 맞춤법", "맞춤법", "표준어 규정", "표준어", "표준 발음법",
    "외래어 표기법", "로마자 표기법", "띄어쓰기",
]

BME_SUPPLEMENTS: list[str] = [
    # 단독으로 자주 언급되는 약어 (용어표에는 묶여 있어 개별 등록이 필요)
    "DNA", "RNA", "mRNA", "tRNA", "rRNA", "cDNA", "miRNA", "siRNA",
    "PCR", "RT-PCR", "qPCR", "ELISA", "SDS-PAGE", "CRISPR", "Cas9",
    "ATP", "NADH", "GPCR", "MHC", "HLA", "CHO", "kLa", "GMP", "GLP", "GCP",
    "IgG", "IgM", "IgA", "IgE", "CAR-T", "iPSC", "AAV", "NGS", "SNP",
    "ECG", "EEG", "EMG", "MRI", "CT", "PET", "ECMO", "CMRR", "SEM", "TEM",
    "Km", "Vmax", "kcat", "p53", "GFP", "His-태그", "IPTG", "ADC", "SaMD",
    # 강의에서 자주 쓰이나 용어표에는 단독으로 없는 기본 개념어
    "효소", "기질", "촉매", "대사", "단백질", "핵산", "지질", "탄수화물",
    "세포", "세포막", "소기관", "유전자", "염색체", "돌연변이",
    "바이러스", "세균", "미생물", "배양", "배지", "멸균", "감염",
    "항체", "항원", "면역", "백신", "T세포", "B세포",
    "현미경", "광학현미경", "전자현미경", "형광현미경",
    "임상시험", "전임상", "1상", "2상", "3상", "무작위 배정", "눈가림", "위약",
    "의료기기", "인공장기", "생체신호", "의료영상", "생체재료", "줄기세포",
    "생명윤리", "생명의료윤리", "연구윤리", "사전 동의",
    # 평가에서 검색이 흔들린 개념들
    "상보적 염기쌍", "선도가닥", "지연가닥", "오카자키 절편",
    "대체 스플라이싱", "인트론", "엑손", "코돈", "안티코돈",
    "에피토프", "항원결정기", "항원제시", "옵소닌화",
    "점착말단", "평활말단", "청백 선별", "코돈 최적화",
    "표적이탈", "표적이탈 효과", "커버리지", "변이 검출",
    "항체약물접합체", "이중특이항체", "면역관문억제제",
    "응력차폐", "생체적합성", "이물반응", "생물막", "혈관화",
    "에일리어싱", "표본화 정리", "동상제거비", "가산평균법",
    "점탄성", "응력완화", "크리프", "볼프의 법칙",
    "산소전달계수", "전단 응력", "스케일업", "관류배양", "유가식 배양",
    "미카엘리스-멘텐", "라인위버-버크", "경쟁적 저해", "비경쟁적 저해",
    "혼합형 저해", "무경쟁적 저해", "알로스테릭",
    "봉입체", "재접힘", "등전점", "단백질 A",
    "치료지수", "초회통과효과", "바이오시밀러", "면역원성",
    # 분자생물학 강의 보충 — KOCW 분자생물학(건양대) 차시 대조에서 확인된 미트리거 어휘.
    # 중심원리 각 단계와 클로닝 실무 어휘가 key_terms에 묶음으로만 있어 빠져 있었다.
    # 세포·유전
    "핵막", "세포벽", "세포질", "종양", "노화", "발암", "체세포 돌연변이",
    "멘델", "멘델 유전", "우열의 법칙", "분리의 법칙", "독립의 법칙",
    "뉴클레오티드", "염기쌍", "퓨린", "피리미딘", "디옥시리보스", "이중나선",
    # 복제·전사·번역
    "복제", "DNA 복제", "복제분기점", "복제 분기점", "헬리케이스", "프라이메이스",
    "텔로미어", "텔로머라아제",
    "전사", "번역", "전사인자", "RNA 중합효소", "중합효소", "터미네이터",
    "유전암호", "리딩 프레임", "리보솜 결합 부위", "샤인-달가노", "샤인 달가노",
    "신장인자", "개시코돈", "종결코돈",
    "유전자 발현", "유전자 발현 조절", "전사 조절",
    "RNA 가공", "스플라이싱", "캡 구조", "폴리A 꼬리",
    # 클로닝·실험 실무
    "화학추출", "페놀 클로로포름", "원심분리", "아가로스 겔",
    "제한효소 지도", "클로닝 벡터", "유전자 재조합", "유전자 클로닝",
    "유전자 라이브러리", "블루 화이트", "스크리닝",
    "중합효소 연쇄반응", "변성", "어닐링", "신장 반응", "프라이머 설계",
    "리가아제", "라이게이스", "DNA 중합효소", "RNA 분해효소", "RNase", "DNase",
    # 생명공학 산물
    "알코올 발효", "알콜 발효", "발효", "대사공학", "대사경로공학",
    "생분해성 플라스틱", "얼음형성 박테리아", "빙핵", "인슐린", "재조합 단백질",
]


# ── 패턴 예외 규칙 ────────────────────────────────────────────────────
# 한글 패턴은 부분 문자열로 매칭하므로, 짧은 용어가 무관한 낱말 안에 박혀
# 오탐을 낸다('음소' ⊂ '음소거', '수요' ⊂ '수요일'). 해당 문맥을 지운 뒤에도
# 패턴이 남아 있을 때만 매칭으로 인정한다. 전공 공용이며, 사전에 있는 패턴만
# 실제로 적용된다.
PATTERN_EXCLUSIONS: dict[str, re.Pattern[str]] = {
    "음소": re.compile(r"음소거"),
    "모음": re.compile(r"(사진|자료|영상|링크)\s*모음|모음집|모음전"),
    "수요": re.compile(r"수요일"),
    "번역": re.compile(r"(자막|통역|실시간|기계|자동)\s*번역|번역\s*(자막|기능|앱|기)"),
    "성조": re.compile(r"성조기"),
    "이두": re.compile(r"이두박근"),
}


# ── 전공 라우터 정의 ───────────────────────────────────────────────────


@dataclass(frozen=True)
class MajorRouterSpec:
    """전공 하나에 대한 라우터 구성."""

    key: str                      # CLI/코드에서 쓰는 짧은 이름
    label: str                    # 사람이 읽는 이름
    index_name: str               # 이 전공이 검색할 인덱스 (config.INDEX_SUBSETS)
    content_glob: str             # tools/ 안 교재 콘텐츠 파일 패턴 (key_terms 출처)
    glossary_dir: Path | None     # glossary JSON이 있는 원본 폴더
    glossary_glob: str            # glossary 파일 패턴
    transliterations: dict[str, str]
    supplements: list[str]
    score_threshold: float        # 전공별 평가로 정한 gate 임계값


# 임계값 근거:
#   ai   0.50 — eval/results_v2.md (negative 100% 차단 / positive 99% 통과)
#   hss  0.45 — eval/results_hss.md (negative 100% / positive 99%)
#   bme  0.45 — eval/results_bme.md (negative 80% / positive 91%; 0.50은 75%만 통과)
MAJOR_ROUTERS: dict[str, MajorRouterSpec] = {
    "ai": MajorRouterSpec(
        key="ai",
        label="인공지능",
        index_name="major_ai",
        content_glob="content_part*.py",
        glossary_dir=DATA_RAW_AI_DIR,
        glossary_glob="ai_glossary*.json",
        transliterations=AI_TRANSLITERATIONS,
        supplements=AI_SUPPLEMENTS,
        score_threshold=0.50,
    ),
    "hss": MajorRouterSpec(
        key="hss",
        label="인문사회",
        index_name="major_humanities_social_sciences",
        content_glob="hss_content_part*.py",
        glossary_dir=DATA_RAW_HSS_DIR,
        glossary_glob="*_glossary*.json",
        transliterations=HSS_TRANSLITERATIONS,
        supplements=HSS_SUPPLEMENTS,
        score_threshold=0.45,
    ),
    "bme": MajorRouterSpec(
        key="bme",
        label="바이오의생명공학",
        index_name="major_biomedical_bioengineering",
        content_glob="bme_content_part*.py",
        glossary_dir=DATA_RAW_BME_DIR,
        glossary_glob="*_glossary*.json",
        transliterations=BME_TRANSLITERATIONS,
        supplements=BME_SUPPLEMENTS,
        score_threshold=0.45,
    ),
}

DEFAULT_MAJOR = "ai"

# 하위 호환: 기존 코드가 참조하던 이름들 (AI 전공 기준)
TRANSLITERATIONS = AI_TRANSLITERATIONS
SUPPLEMENT_CONCEPTS = AI_SUPPLEMENTS
RAG_SCORE_THRESHOLD = MAJOR_ROUTERS[DEFAULT_MAJOR].score_threshold

# 강의 발화의 담화 표지 — 임베딩 질의에서 정보가 없는 조각만 보수적으로 제거
FILLER_PATTERNS = [
    re.compile(r"^(어|음|자|그|저)\s+"),
    re.compile(r"그러니까\s*"),
    re.compile(r"뭐시기\s*"),
    re.compile(r"인가\s+그\s+"),
    re.compile(r"\s+그거\s+"),
    re.compile(r"\s+그게\s+"),
]


@dataclass
class RouteDecision:
    use_rag: bool
    query: str
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    score: float | None = None  # apply_gate 이후 top-1 유사도
    gated_off: bool = False     # score gate로 꺼졌는지
    major: str = DEFAULT_MAJOR
    index_name: str = ""

    def to_json(self) -> dict[str, Any]:
        reason = list(self.reasons)
        if self.gated_off:
            reason.append("SCORE_LOW")
        elif not self.use_rag and not reason:
            reason.append("NO_TRIGGER")
        return {
            "useRag": self.use_rag,
            "query": self.query,
            "reason": reason,
            "major": self.major,
            "index": self.index_name,
        }


def _load_glossary_lexicon(spec: MajorRouterSpec) -> list[tuple[str, str, str]]:
    """(패턴, 정식 용어, reason) 목록 — glossary 전 필드. 없으면 빈 목록."""
    entries: list[tuple[str, str, str]] = []
    if spec.glossary_dir is None or not spec.glossary_dir.exists():
        return entries
    paths = sorted(spec.glossary_dir.glob(spec.glossary_glob))
    if not paths:
        return entries
    terms = json.loads(paths[0].read_text(encoding="utf-8"))["terms"]
    for t in terms:
        patterns = {t["term_ko"], t.get("term_en") or "", t.get("abbr") or ""}
        patterns.update(t.get("aliases", []))
        for p in patterns:
            p = p.strip()
            if len(p) >= 2:
                entries.append((p, t["term_ko"], "GLOSSARY_TERM"))
    return entries


_TERM_PAREN_RE = re.compile(r"^([^(]+?)\s*(?:\(([^)]*)\))?$")


def _load_textbook_lexicon(spec: MajorRouterSpec) -> list[tuple[str, str, str]]:
    """교재 콘텐츠 파일의 장별 key_terms → LECTURE_CONCEPT 패턴."""
    entries: list[tuple[str, str, str]] = []
    tools_dir = ROOT / "tools"
    for part in sorted(tools_dir.glob(spec.content_glob)):
        module_spec = importlib.util.spec_from_file_location(part.stem, part)
        if module_spec is None or module_spec.loader is None:
            continue
        module = importlib.util.module_from_spec(module_spec)
        try:
            module_spec.loader.exec_module(module)
        except Exception:
            continue  # 교재 원본이 없어도 라우터는 동작해야 함
        for ch in getattr(module, "CHAPTERS", []):
            # 절 제목의 머리 개념도 사전에 넣는다. '9.2 기능주의: 사회는 어떻게...'처럼
            # 핵심 개념이 제목에만 있고 key_terms 표에는 빠진 경우가 많다.
            for sec in ch.get("sections", []):
                head = _section_title_concept(sec.get("title", ""))
                if head:
                    entries.append((head, head, "LECTURE_CONCEPT"))
                    for part in _split_slash_term(head):
                        entries.append((part, head, "LECTURE_CONCEPT"))
            for kt in ch.get("key_terms", []):
                match = _TERM_PAREN_RE.match(kt["term"].strip())
                if not match:
                    continue
                ko = match.group(1).strip()
                if len(ko) >= 2:
                    entries.append((ko, ko, "LECTURE_CONCEPT"))
                    # 'mRNA/tRNA/rRNA', '이화작용/동화작용'처럼 슬래시로 묶인 항목은
                    # 개별 용어로도 등록해야 발화에서 하나만 언급돼도 잡힌다.
                    for part in _split_slash_term(ko):
                        entries.append((part, ko, "LECTURE_CONCEPT"))
                for en in (match.group(2) or "").split(","):
                    en = en.strip()
                    if len(en) >= 2:
                        entries.append((en, ko, "LECTURE_CONCEPT"))
                        for part in _split_slash_term(en):
                            entries.append((part, ko, "LECTURE_CONCEPT"))
    return entries


# '1차/2차' 처럼 앞부분이 수식어 조각인 경우를 걸러내기 위한 최소 조건
_GENERIC_PART_RE = re.compile(r"^\d+차$|^[가-힣]$")

# '9.2 기능주의: 사회는 어떻게 유지되는가' → '기능주의'
_SEC_NUM_RE = re.compile(r"^\d+\.\d+\s*")
# 조사·서술로 끝나 단독 개념이 아닌 제목을 배제
_SEC_TAIL_RE = re.compile(r"(는가|한가|인가|까$|기$|법$|것$|다$)")


def _spaced_pattern(src: str) -> re.Pattern[str]:
    """음차 문자열을 글자 사이 공백에 관대한 정규식으로 바꾼다.

    STT는 약어를 '지 디 피', '케이 디 씨'처럼 글자 단위로 띄어 쓰는 일이 많다.
    원래 공백이 있던 자리는 공백을 필수가 아닌 선택으로 둔다.
    """
    chars = [c for c in src if not c.isspace()]
    return re.compile(r"\s*".join(re.escape(c) for c in chars))


def _section_title_concept(title: str) -> str | None:
    """절 제목에서 머리 개념만 뽑는다. 개념으로 보기 어려우면 None.

    콜론이 있으면 앞부분을, 없으면 제목 전체를 후보로 삼되 서술형은 버린다.
    """
    text = _SEC_NUM_RE.sub("", title).strip()
    if not text:
        return None
    head = text.split(":")[0].strip() if ":" in text else text
    # 너무 길거나(문장형) 짧으면 개념어로 보지 않는다
    if not (2 <= len(head) <= 20):
        return None
    if _SEC_TAIL_RE.search(head):
        return None
    return head


def _split_slash_term(term: str) -> list[str]:
    """슬래시로 묶인 용어를 개별 패턴으로 분리한다.

    분리 결과가 너무 짧거나 '1차'처럼 단독으로는 의미가 없는 조각이면 버린다.
    과도 트리거는 2단계 score gate가 걸러내므로 여기서는 보수적으로만 제외한다.
    """
    if "/" not in term:
        return []
    parts: list[str] = []
    for raw in term.split("/"):
        part = raw.strip()
        if len(part) < 2 or _GENERIC_PART_RE.match(part):
            continue
        parts.append(part)
    return parts if len(parts) >= 2 else []


class RagRouter:
    """전공 하나를 담당하는 라우터.

    사용: RagRouter("bme") 또는 RagRouter(major="bme").
    전공을 생략하면 하위 호환을 위해 AI 전공으로 동작한다.
    """

    def __init__(
        self,
        major: str = DEFAULT_MAJOR,
        score_threshold: float | None = None,
    ) -> None:
        if major not in MAJOR_ROUTERS:
            raise ValueError(
                f"알 수 없는 전공: {major} (가능: {', '.join(sorted(MAJOR_ROUTERS))})"
            )
        self.spec = MAJOR_ROUTERS[major]
        self.major = major
        self.index_name = self.spec.index_name
        self.score_threshold = (
            self.spec.score_threshold if score_threshold is None else score_threshold
        )

        # GLOSSARY_TERM을 먼저 넣고, 같은 패턴의 LECTURE_CONCEPT는 무시 (glossary 우선)
        self._lexicon: dict[str, tuple[str, str]] = {}  # 패턴(소문자) → (정식 용어, reason)
        supplements = [(p, p, "LECTURE_CONCEPT") for p in self.spec.supplements]
        for pattern, canonical, reason in (
            _load_glossary_lexicon(self.spec)
            + _load_textbook_lexicon(self.spec)
            + supplements
        ):
            key = pattern.lower()
            if key not in self._lexicon:
                self._lexicon[key] = (canonical, reason)
        # 짧은 한글 패턴의 낱말 내부 매칭 예외 (사전에 있는 것만)
        self._exclusions: dict[str, re.Pattern[str]] = {
            k: v for k, v in PATTERN_EXCLUSIONS.items() if k in self._lexicon
        }
        # ASCII 패턴은 단어 경계 필요 ("AI"가 "said"에 걸리지 않도록)
        self._ascii_res: dict[str, re.Pattern[str]] = {
            k: re.compile(rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])")
            for k in self._lexicon
            if k.isascii()
        }
        # 음차 치환은 긴 패턴 먼저.
        # STT는 약어를 '지 디 피'처럼 글자마다 띄어 쓰는 일이 잦으므로,
        # 각 글자 사이에 공백이 있어도 잡히도록 정규식으로 만든다.
        self._translit: list[tuple[re.Pattern[str], str]] = [
            (_spaced_pattern(src), dst)
            for src, dst in sorted(
                self.spec.transliterations.items(),
                key=lambda kv: len(kv[0]),
                reverse=True,
            )
        ]

    # ── 1단: rule trigger + query 생성 ────────────────────────────────
    def route(self, sentence: str) -> RouteDecision:
        normalized = self.normalize(sentence)
        lowered = normalized.lower()

        matched: dict[str, str] = {}  # 정식 용어 → reason
        for pattern, (canonical, reason) in self._lexicon.items():
            if pattern in self._ascii_res:
                hit = bool(self._ascii_res[pattern].search(lowered))
            else:
                hit = pattern in lowered
                if hit and pattern in self._exclusions:
                    # 예외 문맥을 지운 뒤에도 남아 있어야 진짜 언급으로 본다
                    hit = pattern in self._exclusions[pattern].sub(" ", lowered)
            if hit and canonical not in matched:
                matched[canonical] = reason
            elif hit and reason == "GLOSSARY_TERM":
                matched[canonical] = reason  # glossary 우선

        reasons = sorted({r for r in matched.values()})
        # 질의 = 정규화 문장 + (문장에 아직 없는) 정식 용어 병기
        extra_terms = [t for t in matched if t.lower() not in lowered]
        query = normalized if not extra_terms else f"{normalized} {' '.join(extra_terms)}"
        return RouteDecision(
            use_rag=bool(matched),
            query=query,
            reasons=reasons,
            matched_terms=sorted(matched),
            major=self.major,
            index_name=self.index_name,
        )

    def normalize(self, sentence: str) -> str:
        """음차 → 코퍼스 표기 치환 + 담화 필러 제거.

        음차는 글자 사이 공백을 허용해 매칭한다('지 디 피' → 'GDP').
        """
        text = sentence.strip()
        for pattern, dst in self._translit:
            text = pattern.sub(dst, text)
        for pattern in FILLER_PATTERNS:
            text = pattern.sub(" ", text)
        return re.sub(r"\s+", " ", text).strip()

    # ── 2단: score gate ───────────────────────────────────────────────
    def apply_gate(self, decision: RouteDecision, top1_score: float) -> RouteDecision:
        decision.score = top1_score
        if decision.use_rag and top1_score < self.score_threshold:
            decision.use_rag = False
            decision.gated_off = True
        return decision

    # ── ai-worker 포팅용 lexicon 내보내기 ─────────────────────────────
    def export_lexicon(self, path: Path) -> None:
        payload = {
            "major": self.major,
            "label": self.spec.label,
            "index": self.index_name,
            "score_threshold": self.score_threshold,
            "transliterations": self.spec.transliterations,
            "lexicon": [
                {"pattern": k, "canonical": v[0], "reason": v[1]}
                for k, v in sorted(self._lexicon.items())
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_routers() -> dict[str, RagRouter]:
    """전공 라우터를 한 번에 만들어 둔다 (워커 기동 시 1회)."""
    return {key: RagRouter(key) for key in MAJOR_ROUTERS}


if __name__ == "__main__":
    # 수동 확인: python src/router.py --major bme "그 피시알 그거 몇 단계라 했죠"
    import argparse

    parser = argparse.ArgumentParser(description="전공별 라우터 수동 확인")
    parser.add_argument("--major", choices=sorted(MAJOR_ROUTERS), default=DEFAULT_MAJOR)
    parser.add_argument("sentence", nargs="*", help="STT 문장")
    parser.add_argument(
        "--export", type=Path, default=None, help="lexicon JSON 내보내기 경로"
    )
    args = parser.parse_args()

    router = RagRouter(args.major)
    if args.export:
        router.export_lexicon(args.export)
        print(f"lexicon 저장: {args.export} ({len(router._lexicon)}개 패턴)")

    sentence = " ".join(args.sentence) or "컨볼루션이 이미지에서 특징을 뽑아낸다고 했죠"
    decision = router.route(sentence)
    print(f"[{router.spec.label}] 사전 {len(router._lexicon)}개 / 임계값 {router.score_threshold}")
    print(json.dumps(decision.to_json(), ensure_ascii=False, indent=2))
    print(f"matched: {decision.matched_terms}")
