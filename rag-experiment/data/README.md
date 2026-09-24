# RAG Data Layout

This directory contains raw source material and generated chunk data used by
the RAG experiments.

## Folders

- `raw/<major>/`: source PDFs and JSON files, one folder per major
  - `raw/ai/`: AI major (lecture slides, concept note, textbook, glossary)
  - `raw/Humanities_Social_Sciences/`: Humanities & Social Sciences major (textbook)
  - `raw/Biomedical_Bioengineering/`: Biomedical & Bioengineering major (textbook + field metadata sidecar)
- `raw_distractor/`: optional distractor PDFs
- `chunks/chunks.jsonl`: generated chunks with `chunk_id`, `source`, `doc_type`, `text`, and `metadata`

Generate chunks with:

```bash
python src/ingest.py
```

## Majors and Separation

Majors must not leak into each other's index. Separation is enforced by
`doc_type`: each major uses its own `doc_type` values, and
`INDEX_SUBSETS` in `src/config.py` maps an index name to the `doc_type`s it
may contain. `chunk_id` prefixes are also distinct so IDs stay globally unique
in the shared `chunks.jsonl`.

| Major | Source | `doc_type` | ID prefix |
| --- | --- | --- | --- |
| AI | lecture slides | `lecture_slide` | `lecNN_` |
| AI | concept note | `concept_doc` | `concept_` |
| AI | textbook | `textbook` | `tb_` |
| AI | glossary | `glossary` | `glossary_` |
| Humanities & Social Sciences | textbook | `hss_textbook` | `hsstb_` |
| Humanities & Social Sciences | concept note | `hss_concept_doc` | `hssconcept_` |
| Biomedical & Bioengineering | textbook | `bme_textbook` | `bmetb_` |
| Biomedical & Bioengineering | concept note | `bme_concept_doc` | `bmeconcept_` |
| (any) | distractor | `distractor` | `distr_` |

### Field metadata (BME only)

`tools/build_bme_textbook.py` writes a sidecar `*_메타.json` next to the PDF
mapping each chapter number to a subject field (`생화학`, `면역학`,
`생물공정공학`, …). `src/ingest.py` joins it by chapter number so every
`bme_textbook` chunk carries `metadata.field` / `metadata.field_en`, which can
be used for filtering or routing at query time. Regenerating the PDF refreshes
the sidecar; if it is missing, ingestion still succeeds but without field tags.

> `hss_concept_doc` is wired up but currently has no source file. Dropping
> `인문사회_개념_지식자료.pdf` into `raw/Humanities_Social_Sciences/` and
> re-running `src/ingest.py` is enough to include it.

## Indexes

Built per `(index, model)` into `indexes/<index>/<model>/`:

```bash
python src/embed.py --model {kure|bge-m3|openai} --index <index>
```

| Index | Contains | Chunks |
| --- | --- | --- |
| `major_ai` | `glossary`, `concept_doc`, `textbook` | 310 |
| `major_humanities_social_sciences` | `hss_concept_doc`, `hss_textbook` | 151 |
| `major_biomedical_bioengineering` | `bme_concept_doc`, `bme_textbook` | 150 |
| `lecture_kim_i2a` | `lecture_slide` | 30 |

Omitting `--index` builds a combined index over every chunk into
`indexes/<model>/`, which mixes majors — use a named index for per-major RAG.

## Chunk ID Conventions

| Prefix | Doc type | Example |
| --- | --- | --- |
| `lecNN_` | lecture slides | `lec02_p03_06` |
| `concept_` | concept note | `concept_ch4_s3` |
| `glossary_` | glossary entry | `glossary_task_environment` |
| `tb_` | textbook | `tb_ch08_s4` |
| `hsstb_` | HSS textbook | `hsstb_ch18_s2` |
| `hssconcept_` | HSS concept note | `hssconcept_ch3_s1` |
| `distr_` | distractor source | `distr_<slug>_...` |

### Textbook IDs

Applies to both `tb_` (AI) and `hsstb_` (HSS):

- `tb_chNN_intro`: chapter introduction
- `tb_chNN_sM`: section body
- `tb_chNN_sM_2`: overflow split of the same section
- `tb_chNN_summary`: chapter summary
- `tb_chNN_terms`: chapter term list

## Inspecting a Chunk

```powershell
Select-String -Path data\chunks\chunks.jsonl -Pattern '"tb_ch08_s4"' | % Line
```

```bash
python src/search.py --model kure --index major_humanities_social_sciences --query "훈민정음의 제자 원리는?"
```
