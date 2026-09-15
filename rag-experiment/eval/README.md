# Evaluation Assets

This directory stores query sets, notes, and result summaries for the RAG
evaluation workflow.

## Key Files

| File | Purpose |
| --- | --- |
| `queries_positive.json` | Main positive evaluation set |
| `queries_hard.json` | Hard paraphrase, noise, and negative cases |
| `queries_textbook.json` | Textbook-focused evaluation set |
| `queries_positive_v2.json` / `queries_hard_v2.json` | Revised answer mappings after textbook ingestion |
| `queries_textbook_hard.json` | Hard variants of textbook questions |
| `queries_hss_positive.json` | Humanities & Social Sciences positive set (definition/comparison/principle) |
| `queries_hss_hard.json` | HSS paraphrase, STT-noise, and negative cases |
| `queries_bme_positive.json` | Biomedical & Bioengineering positive set (definition/comparison/principle) |
| `queries_bme_hard.json` | BME paraphrase, STT-noise, and negative cases |
| `router_test_sentences.json` | Router-only sentence classification cases |
| `results*.md` | Captured evaluation results |
| `_miss_analysis*.txt` | Notes on misses and answer corrections |

## Query Sets by Major

Each major has its own query set targeting its own chunk-ID prefix, so a set
must be run against the matching index (see `data/README.md`).

| Major | Query files | Answer IDs | Index |
| --- | --- | --- | --- |
| AI | `queries_positive*.json`, `queries_hard*.json`, `queries_textbook*.json` | `glossary_`, `concept_`, `tb_` | `major_ai` |
| Humanities & Social Sciences | `queries_hss_positive.json`, `queries_hss_hard.json` | `hsstb_` | `major_humanities_social_sciences` |
| Biomedical & Bioengineering | `queries_bme_positive.json`, `queries_bme_hard.json` | `bmetb_` | `major_biomedical_bioengineering` |

## Running Evaluation

```bash
# AI (combined index)
python src/evaluate.py \
  --queries eval/queries_positive.json eval/queries_hard.json \
  --output eval/results.md

# Humanities & Social Sciences (separated index)
python src/evaluate.py \
  --queries eval/queries_hss_positive.json eval/queries_hss_hard.json \
  --index major_humanities_social_sciences \
  --output eval/results_hss.md

# Biomedical & Bioengineering (separated index)
python src/evaluate.py \
  --queries eval/queries_bme_positive.json eval/queries_bme_hard.json \
  --index major_biomedical_bioengineering \
  --output eval/results_bme.md
```

On Windows, pass `--output NUL` to print the report without writing a file
(omitting `--output` overwrites the default `eval/results.md`).

`--index` restricts retrieval to one major's index; omit it to search the
combined index over all chunks.

Additional scripts:

- `python src/evaluate_router.py`
- `python src/evaluate_split.py`

## Notes

- Negative cases use empty `answer_chunk_ids`.
- Textbook query sets target `tb_*` chunk IDs.
- Versioned query files preserve older answer mappings for comparison.
