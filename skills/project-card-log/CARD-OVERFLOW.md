# Project-card overflow → continuation sub-cards

A project card is append-only from the cluster, so over a long campaign it can
grow past Heptabase's per-card size cap. `append_card.py` (this dir) handles the
**append side**; consolidating a chain back to one card is the **Mac-only merge
side** (spec below), because it needs overwrite/delete which the append-only `hb`
bridge lacks.

## The chain model

    entry (母卡)  →  續1  →  續2  →  …  →  tail

- The `.heptabase-card` marker / registry / `resolve_card.py` always point at the
  **ENTRY** card. Its identity never moves.
- Each non-tail card ends with a machine-parseable continuation link:

      ▶ **續卡（本卡已達容量上限）**：[[card:<child_id>]]

  Sentinel constant: `LINK_MARK = "續卡（本卡已達容量上限）"` in `append_card.py`.
  `hb read` / `heptabase note read` both emit card links back as
  `[[card:<uuid>]]`, so the chain is recoverable from card bodies alone.

## Append side (done — `append_card.py`)

`python3 append_card.py --card <ENTRY_ID> --content-file section.md`
1. walk entry → … → tail (cycle-guarded, ≤ CHAIN_MAX).
2. if `est_stored(tail) + est_stored(new) + margin ≤ spill_threshold` → append
   to tail（stored-representation units, see Config below）.
3. else → create a continuation child (`{entry_title} · 續 N`, opens with a
   `母卡：[[card:<entry_id>]]` back-ref), put the new section there, and append
   the continuation link to the old tail.
- Transports: obsidian (files, no cap → always plain append) / heptabase CLI
  (child tagged) / hb bridge (child **untagged** → flagged in output `note`).
- Config: `heptabase.collections.projects.{char_cap,spill_threshold,overflow_spill}`
  (defaults 100000 / 80000 / **false**). Sizes are measured in the STORED
  (ProseMirror-serialized) representation: the append side estimates it from
  markdown via `est_stored_len()`（deliberately errs high）, the merge side
  measures the as-built PM JSON directly; threshold < cap leaves headroom for
  UUID assignment on save and future appends.

> ⚠️ **Enablement order.** `overflow_spill` is **OFF by default**. While off,
> an append that WOULD overflow fails fast with "整併母卡 on the Mac first" and
> **moves no content out of the entry** — because a `project-card-merge` that
> isn't yet chain-aware would drop a child's `📥` content when it rewrites the
> entry. Turn `overflow_spill=true` **only after** the merge side below is
> implemented and shipped. (append_card.py is safe to land now; the spill just
> stays dormant until then.)

## Merge side (DONE — `project-card-merge`, Mac-only)

Implemented in `project-card-merge/merge_lib.py`（chain/ chain_dumps/
child_payload/ find_orphans/ finalize_chain/ cleanup_children；scan 已
chain-aware）. The steps below are the as-built behavior:

1. **Detect the chain.** From the entry, follow `[[card:<id>]]` after each
   `續卡（本卡已達容量上限）` sentinel to collect `[entry, 續1, …, tail]`.
   Reuse `append_card.parse_continuation()` (importable, stdlib).
2. **Pull children back in order.** For each child, take its body MINUS the
   auto-header (`# … · 續 N` + the `母卡：[[…]]` back-ref line) and merge those
   sections into the entry exactly like a normal append block (same
   dedup/supersede/`🔍`-fold rules the merge already applies).
3. **Strip the continuation links** from every card as they're absorbed (remove
   each `▶ 續卡…` block from the entry/intermediate bodies).
4. **Tag the untagged cluster children** before deleting — or skip if deleting:
   `heptabase tag add --card-id <child> --tag-name project` (bridge left them
   untagged). Do this so a mid-merge crash leaves them discoverable.
5. **Delete (or archive) the now-empty children.** Needs overwrite/delete →
   Mac-only. If your policy is archive-not-delete, move them to an `archive`
   collection and drop them from the chain.
6. **Re-spill if STILL over cap.** `finalize_chain()` spills whole H2
   sections into a fresh continuation chain（entry 留前段；children created
   & tagged BEFORE the entry saves — crash 只留可發現的 orphan，不丟內容）—
   the no-loss default, so a merge is NEVER forced to condense paper-grade
   content. When the split would read better as a topic/act re-split, the
   overview-graph resplit (`overview-graph/scripts/resplit.py`) remains the
   human-navigable alternative（ask the user first）.

7. **Op5 appends are chain-safe.** overview-graph Operation 5（research-gap
   analysis）appends its `🔍` section through `append_card.py` too, so it
   lands on the chain tail and spills instead of overflowing.

### Edge cases for the merge side
- **Partial chain** (cluster created 續1 but crashed before linking): a child
  with a `母卡:` back-ref but no inbound link from any tail — scan the projects
  collection for orphan `… · 續 N` cards referencing this entry.
- **Idempotency**: re-running merge on an already-consolidated entry (no chain)
  must be a no-op.
- **Don't lose figures/colors**: children carry markdown only; if a child ever
  holds figures, run them through the same colorize/figure-preserve path.

## Backend capability matrix
| op | obsidian | heptabase CLI (Mac) | hb bridge (cluster) |
|---|---|---|---|
| read / create / append | ✓ | ✓ | ✓ |
| tag child | ✓ (frontmatter) | ✓ | ✗ → Mac follow-up |
| overwrite / delete (merge) | ✓ | ✓ | ✗ (Mac-only) |
