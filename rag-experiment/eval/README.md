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
| `router_test_sentences.json` | Router-only sentence classification cases |
| `results*.md` | Captured evaluation results |
| `_miss_analysis*.txt` | Notes on misses and answer corrections |

## Running Evaluation

```bash
python src/evaluate.py \
  --queries eval/queries_positive.json eval/queries_hard.json \
  --output eval/results.md
```

Additional scripts:

- `python src/evaluate_router.py`
- `python src/evaluate_split.py`

## Notes

- Negative cases use empty `answer_chunk_ids`.
- Textbook query sets target `tb_*` chunk IDs.
- Versioned query files preserve older answer mappings for comparison.
