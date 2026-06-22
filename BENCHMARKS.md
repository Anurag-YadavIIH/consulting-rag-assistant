# ConsultRAG — Retrieval Benchmarks

Recorded reference points for retrieval quality, so future changes to the
pipeline are measured against logged numbers, not memory. **Append a new
dated entry each time the eval set or retrieval pipeline changes
meaningfully — don't overwrite old entries.**

## How to reproduce an entry

```bash
docker compose up -d
python scripts/migrate_pg.py --dim 384 --table chunks_baseline

python scripts/ingest.py --path data/sample --engagement acme --clearance 2 --embedder local
python scripts/ingest.py --path data/sample --engagement acme --clearance 2 \
    --embedder local --store pgvector --table chunks_baseline

python scripts/run_eval.py --embedder local
python scripts/run_eval.py --embedder local --store pgvector --table chunks_baseline
```

`chunks_baseline` is a table dedicated to this benchmark, separate from
whatever `chunks` table you use for day-to-day demos/testing — re-running the
commands above never touches your other data.

---

## 2026-06-21 — initial baseline (read the caveat before trusting these numbers)

| Field | Value |
|---|---|
| Gold set | `eval/eval_set.jsonl` — **4 questions**, spanning **2 of 3** sample documents (`acme_research.txt`, `globex_research.txt`; `deck.pptx` not covered at all) |
| Embedder | `local` (sentence-transformers `BAAI/bge-small-en-v1.5`, dim 384) |
| Reranker | none (`NoOpReranker`, default — `--rerank` not used for this run) |
| Retrieval | hybrid dense + BM25 via RRF (`HybridRetriever`, default `RRF_K=60`) |
| k | 5 |

| Backend | hit@5 | recall@5 | MRR |
|---|---|---|---|
| numpy (default) | 0.5 | 0.5 | 0.5 |
| pgvector (`chunks_baseline` table) | 0.5 | 0.5 | 0.5 |

**Backends agree exactly.** This is the equivalence check working on real,
non-zero numbers for the first time — previously masked entirely by the
chunk-ID path-separator bug (fixed the same day this baseline was recorded;
both backends reported 0.0/0.0/0.0 before that fix, which was a bug, not a
quality signal).

**Caveat — this is not yet a meaningful quality signal.** With 4 questions,
hit@k/recall@k/MRR can only ever land on {0, 0.25, 0.5, 0.75, 1.0}; there's no
statistical resolution, and a single retrieval swinging one way or the other
moves the score by 25 points. Read this entry as "the harness works and the
two backends agree," not "retrieval is 50% as good as it should be." See
README → Tests & evaluation for the gold-set growth recommendation before
the next entry in this file should be treated as a real baseline.

**Generation faithfulness / answer-relevancy: not measured — not implemented.**
`consultrag.eval.evaluate()` only scores retrieval (hit@k/recall@k/MRR); no
RAGAS-style or LLM-judge generation eval exists in the codebase yet. Tracked
in the README roadmap as a planned, not-yet-built item.

---

## 2026-06-21 — chunk-ID scheme fixed; same gold set, numbers move to 1.0

**Root cause found the same day, by diagnosing this entry's own 0.5 scores:**
`chunking.py`'s fallback locator (used whenever a section has no explicit one
— every plain `.txt`/`.md` file) was a *batch-wide* `enumerate()` index, not a
per-file one. `globex_research.txt`'s real chunk_id depended on how many
other files were ingested alongside it and their alphabetical sort order —
it was `...globex_research.txt#3::0` when ingested with the rest of
`data/sample`, not the `#0::0` the gold set assumed. That ID is also a
PgVector key and an audit-log reference, so the instability wasn't just an
eval-harness annoyance.

**Fix:** the fallback locator is now a per-document counter keyed by
`source_path`, never a batch position. Ingesting a file alone vs. alongside
others (regardless of sort order) now produces identical chunk_ids for it —
covered by a regression test
(`test_chunk_id_for_a_file_is_independent_of_other_files_in_the_batch`).

**Gold set: unchanged.** `eval/eval_set.jsonl`'s existing labels
(`globex_research.txt#0::0`) were already correct under the *intended*
per-file scheme — they just never matched what the buggy implementation
actually produced. Confirmed by re-ingesting and diffing literal chunk_ids;
no edit was needed.

| Backend | hit@5 | recall@5 | MRR |
|---|---|---|---|
| numpy | 1.0 | 1.0 | 1.0 |
| pgvector (`chunks_baseline`, table truncated and re-ingested) | 1.0 | 1.0 | 1.0 |

Up from 0.5/0.5/0.5 in the entry above, on the *same* 4-question gold set and
the *same* embedder — both previously-failing questions now hit, and the two
backends still agree exactly. The numbers moving is the actual proof here:
ID scheme → labels → metrics are finally consistent end to end. The
4-question caveat from the previous entry still applies in full — 1.0 here
means "all 4 hit," not "retrieval is perfect"; it's a small, easy gold set on
its own near-verbatim source text. Don't treat this as a ceiling once the
gold set grows.

---

## 2026-06-21 — gold set expanded to 31 questions; metrics that actually discriminate

**Gold set composition** (`eval/eval_set.jsonl`, every `relevant_id` validated
against a fresh ingest via `scripts/validate_eval_set.py` — zero bad labels,
and all 6 multi-source questions have every labeled chunk confirmed present
in top-k retrieval, not just asserted):

| Category | Count | Scored on retrieval? |
|---|---|---|
| `answerable` | 25 (includes 6 multi-source, 2-3 `relevant_ids` each) | yes |
| `partial` (context exists, specific detail doesn't — generation should abstain on it) | 2 | yes |
| `unanswerable` (no chunk can legitimately satisfy the question) | 4 | **no — excluded** |
| **Total** | **31** | **27 scored** |

Coverage added beyond the original 4 questions: `deck.pptx` speaker notes
(`is_notes=True`, previously zero coverage), paraphrases with low keyword
overlap with their source chunk (embedding-robustness, not keyword-match),
and genuine multi-source synthesis questions (each chunk confirmed
non-redundant — no padding).

**Leading with the metric that actually means something here, not the one
that looks best:**

| Metric | numpy | pgvector (`chunks_baseline`) |
|---|---|---|
| **MRR@5** | **0.926** | **0.926** |
| hit@1 / recall@1 (diagnostic, k below corpus size) | 0.852 / 0.735 | 0.852 / 0.735 |
| hit@5 / recall@5 | 1.0 (saturated — see below) | 1.0 (saturated — see below) |

Both backends agree exactly on every metric at every k tested.

**Why hit@5/recall@5 are reported last, not first:** the corpus is 4 chunks
total. At k=5 (≥ corpus size), every query's top-5 mathematically contains
*all 4 chunks*, so hit@k and recall@k are saturated at 1.0 by construction
for any k≥4 — they carry no signal at this corpus size and would say "1.0"
regardless of retrieval quality. MRR is rank-sensitive and isn't saturated
the same way: 0.926 means roughly 1 in 13 scored questions doesn't rank its
correct chunk first (still found, just not ranked best). Dropping k to 1
confirms the corpus *can* discriminate when k is small enough — hit@1 0.852,
recall@1 0.735 — but k=1 isn't the metric `run_eval.py` reports by default
and shouldn't be over-read either; it's included here as a diagnostic, not a
new headline number.

**Known limitation:** these metrics only become broadly meaningful once the
corpus is large enough that top-k is a small fraction of total chunks.
That requires expanding `data/sample` itself, not just the question count —
tracked separately, not done here.

---

## 2026-06-22 — corpus expanded to 214 chunks; first representative baseline

**This entry supersedes the 4-chunk and 31-question entries above as the
reference baseline going forward.** Those earlier entries were never wrong
for what they measured (the harness, then the ID-scheme fix, then a harder
gold set on a still-tiny corpus) — they're kept, not deleted, per this file's
own append-only convention — but none of them describe the real system: the
corpus was 98.1% `data/sample` until now. `data/corpus/` (4 FDA PDFs, 12
PubMed abstracts, fetched via `scripts/fetch_corpus.py`) brings the real
chunk count to 214, of which `data/sample` is now under 2%.

**Gold set composition** (`eval/eval_set.jsonl`, 60 questions — every
`relevant_id` re-validated against a fresh ingest of the full corpus via
`scripts/validate_eval_set.py`):

| Category | Count | Scored on retrieval? |
|---|---|---|
| `answerable` (includes 10 multi-source, 2–3 `relevant_ids` each) | 50 | yes |
| `partial` (context exists, specific detail doesn't) | 4 | yes |
| `unanswerable` (no chunk can legitimately satisfy the question) | 6 | **no — excluded** |
| **Total** | **60** | **54 scored** |

Two labels were corrected during a dedicated audit of every partial/
unanswerable item *before* committing (not after — caught pre-commit):

- A "partial" question about Medivis NeuroAlign's ground-truth accuracy was
  reclassified to **answerable** — the labeled chunk's full text (read past
  what an earlier 500-char preview showed) actually states the threshold
  ("system error remains within 2mm and 2 degrees").
- An "unanswerable" question about the FDA Neurological Devices Panel's
  final classification decision was reclassified to **partial** — the
  highest-scoring chunk in the entire corpus on this exact topic discusses
  the pending classification process and its three candidate outcomes
  (Class I/II/III) without stating which was chosen, the same pattern as the
  earlier "incumbent device makers" partial case.
- One remaining unanswerable item (patient enrollment in "the clinical
  trial" the BCI guidance "describes") is a deliberate **false-premise
  trap** — the guidance is recommendations text for future sponsor trials,
  not a report of one specific completed trial — noted explicitly in its
  `note` field so a future faithfulness eval can score "reject the premise"
  as correct, distinct from plain abstention on a missing number.

**Metrics, both backends agreeing exactly:**

| Metric | numpy | pgvector (`chunks_baseline`) |
|---|---|---|
| hit@5 | 0.833 | 0.833 |
| recall@5 | 0.796 | 0.796 |
| **MRR@5** | **0.682** | **0.682** |
| hit@1 / recall@1 | 0.574 / 0.534 | 0.574 / 0.534 |

**hit@5/recall@5 are no longer saturated** — at 214 chunks, top-5 is ~2.3% of
the corpus, not the whole thing. This is the real signal the corpus
expansion was for: MRR@5 dropped from 0.926 (4-chunk corpus) to 0.682, and
hit@5/recall@5 dropped from the meaningless 1.0 ceiling to 0.833/0.796 —
numbers that can actually move in either direction as the pipeline changes,
which is the point of having a baseline at all.

**Known multi-source gaps (documented, not hidden):** 7 of the 14
multi-source questions have at least one labeled chunk missing from top-5.
4 are the original `data/sample` gaps (unchanged from the 31-question entry).
3 are new, all in the FDA-only subset — e.g. "Compare the localization
approach of the Medivis NeuroAlign with the mechanism of action of the
Fasikl Felix device" retrieves Medivis content but not Fasikl's. Every one
was individually re-verified: the labels are accurate (the cited chunk
genuinely supports its part of the answer), the gap is retrieval failing to
surface a second relevant document once it's competing against ~200
unrelated chunks — not a labeling error. Cross-document synthesis is
measurably harder at this corpus size than it was at 4 chunks; that's a
property of the system being measured now, not noise in the measurement.

**Generation faithfulness / answer-relevancy: still not measured — still not
implemented.** Unchanged from every prior entry.

---

## 2026-06-22 — retrieval ablation: does hybrid + rerank earn their place?

Measurement only — no retrieval defaults changed. Same committed 60-question
gold set, same scored subset (54 of 60; 6 `unanswerable` excluded), same
embedder (`local`), same numpy index (214 chunks). Reported on the metrics
that actually discriminate at this corpus size — MRR@5 and hit@1 — per the
"why hit@5/recall@5 are reported last" note in the entry above.

| Config | MRR@5 | Δ vs dense-only | hit@1 | Δ vs dense-only | recall@1 |
|---|---|---|---|---|---|
| 1. dense-only (vector, no BM25, no rerank) | 0.766 | — | 0.667 | — | 0.608 |
| 2. hybrid (dense + BM25 via RRF), no rerank | 0.682 | **−0.084** | 0.574 | **−0.093** | 0.534 |
| 3. hybrid + cross-encoder rerank (current default) | **0.796** | +0.030 | **0.722** | +0.055 | 0.651 |

**Called out honestly, as asked: stage 2 (BM25 fusion) does not help on this
corpus — it actively hurts.** Adding BM25 via RRF on top of dense-only makes
every measured number worse. Stage 3 (reranking) is what earns hybrid's
place: it doesn't just add value on top of hybrid, it overcomes hybrid's own
regression and nets out ahead of dense-only — but only once reranking is
actually applied. **If reranking is ever disabled (cost, latency), the
current default retriever (hybrid, no rerank) would score worse than the
simpler dense-only baseline would.**

**Single-source vs. multi-source breakdown** (44 single-source / 10
multi-source of the 54 scored) — checked explicitly because the corpus-wide
baseline already documents 7 known multi-source retrieval gaps:

| Config | single hit@1 | single MRR@5 | multi hit@1 | multi MRR@5 |
|---|---|---|---|---|
| 1. dense-only | 0.682 | 0.779 | 0.600 | 0.708 |
| 2. hybrid, no rerank | 0.614 | 0.722 | 0.400 | 0.508 |
| 3. hybrid + rerank | 0.727 | 0.807 | 0.700 | 0.750 |

**BM25 fusion hurts multi-source questions roughly 3x worse than
single-source** (hit@1 drops 0.068 for single-source vs. 0.200 for
multi-source, going from config 1 to 2) — comparative/synthesis-style
questions apparently confuse BM25's exact-term matching more than they
confuse dense embeddings, and RRF's equal weighting lets that drag down the
fused ranking. Reranking again more than compensates for both subsets,
ending net-positive even for multi-source (0.700 vs. dense-only's 0.600).

**Not changing any defaults from this — reporting only, as instructed.** The
current default (`HybridRetriever` + `NoOpReranker`, i.e. row 2 of the first
table) is exactly what the corpus-wide baseline above measured. This
ablation shows that default is currently being carried entirely by users who
opt into `--rerank`; anyone running without it is worse off than the naive
dense-only baseline this whole stack was meant to improve on.

---

## 2026-06-22 — config 4 (dense-only + rerank): hypothesis tested, does NOT hold

Same methodology, same 54-question scored subset, same index. Added the one
cell missing from the table above — reranking applied directly to the
dense-only baseline, BM25/RRF skipped entirely — to test whether it beats
the current default now that BM25-without-rerank is a known regression.

| Config | MRR@5 | hit@1 | recall@1 | hit@5 | recall@5 |
|---|---|---|---|---|---|
| 1. dense-only | 0.766 | 0.667 | 0.608 | 0.907 | 0.836 |
| 2. hybrid, no rerank | 0.682 | 0.574 | 0.534 | 0.833 | 0.796 |
| 3. hybrid + rerank (current default) | **0.796** | **0.722** | **0.651** | 0.907 | 0.867 |
| 4. dense-only + rerank | 0.785 | 0.685 | 0.623 | **0.926** | **0.877** |

**Hypothesis does not hold.** Config 4 beats config 3 only on the two
already-near-saturated metrics (hit@5, recall@5 — see the entry above on why
those don't discriminate well at this corpus size). On the metrics that
actually discriminate, **config 3 (current default) wins**: MRR@5 0.796 vs.
0.785, hit@1 0.722 vs. 0.685, recall@1 0.651 vs. 0.623.

**Single/multi breakdown — this is where the gap is real, not noise:**

| Config | single hit@1 | single MRR@5 | multi hit@1 | multi MRR@5 |
|---|---|---|---|---|
| 1. dense-only | 0.682 | 0.779 | 0.600 | 0.708 |
| 2. hybrid, no rerank | 0.614 | 0.722 | 0.400 | 0.508 |
| 3. hybrid + rerank | 0.727 | 0.807 | **0.700** | **0.750** |
| 4. dense-only + rerank | 0.705 | 0.803 | 0.600 | 0.708 |

For single-source questions, config 3 and 4 are nearly tied (within 0.022 on
hit@1). **For multi-source questions, config 4 is identical to plain
dense-only** (0.600/0.708 both rows) — reranking dense-only's candidate pool
adds nothing for multi-source here, while config 3 is +0.100 hit@1 / +0.042
MRR@5 ahead of dense-only.

**Why:** the earlier entry showed BM25-without-rerank has bad *ranking*
quality, especially for multi-source. But ranking quality and *recall
contribution to the candidate pool* are different things. Hybrid's fused
pool (top-20 before reranking) apparently contains relevant chunks for
multi-source questions that dense-only's top-20 never surfaces at all —
reranking can only promote what's in the pool it's given. Dense-only +
rerank can't recover a candidate that dense-only never retrieved in the
first place; hybrid's fusion step, despite ranking those candidates poorly
on its own, still gets them into the pool where the reranker can find them.

**Conclusion: not proposing the default change.** The data was the test, and
it falsified the hypothesis. **Keeping `HybridRetriever` + opt-in
`--rerank` as the default retrieval path, unchanged.** The actionable
finding from both entries together is narrower than "drop BM25": BM25's
*own ranking* is a net negative and should not be trusted standalone, but
its *contribution to the fused candidate pool* is specifically what gives
the reranker enough material to do well on multi-source questions. Dropping
BM25 would trade that away for no measured gain on the metrics that matter
here.
