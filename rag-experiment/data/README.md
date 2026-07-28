# RAG Data Layout

This directory contains raw source material and generated chunk data used by
the RAG experiments.

## Folders

- `raw/`: source PDFs and JSON files
- `raw_distractor/`: optional distractor PDFs
- `chunks/chunks.jsonl`: generated chunks with `chunk_id`, `source`, `doc_type`, `text`, and `metadata`

Generate chunks with:

```bash
python src/ingest.py
```

## Chunk ID Conventions

| Prefix | Doc type | Example |
| --- | --- | --- |
| `lecNN_` | lecture slides | `lec02_p03_06` |
| `concept_` | concept note | `concept_ch4_s3` |
| `glossary_` | glossary entry | `glossary_task_environment` |
| `tb_` | textbook | `tb_ch08_s4` |
| `distr_` | distractor source | `distr_<slug>_...` |

### Textbook IDs

- `tb_chNN_intro`: chapter introduction
- `tb_chNN_sM`: section body
- `tb_chNN_sM_2`: overflow split of the same section
- `tb_chNN_summary`: chapter summary
- `tb_chNN_terms`: chapter term list

## Inspecting a Chunk

```powershell
Select-String -Path data\chunks\chunks.jsonl -Pattern '"tb_ch08_s4"' | % Line
```
