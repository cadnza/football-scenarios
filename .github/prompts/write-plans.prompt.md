---
name: Write Plans
description: Write high-level tactical plans
tools: [vscode, execute, read, agent, edit, search, web, browser, new, todo]
agent: agent
---

# Task: Generate 30 YAML tactical plans and save them in `./plans`

You are a file-capable agent. Your job is to **generate 30 new YAML files** that conform to the JSON Schema at `./schemas/plan.json`, save them under `./plans/`, and continue the **global ordering** described below. Your output is solely the files—no extra text unless a summary is requested.

---

## Source of truth
- The schema is located at **`./schemas/plan.json`**. Use your own validation tools to ensure every new file conforms to this schema.
- Read the tactic and level **enum lists and their order** directly from the schema. Do not hardcode them.

## Validation

Use `tools/validate_plans.py` to validate your work (takes no arguments, must exit cleanly). Use `.venv/bin/python` as the Python interpreter to run `tools/validate_plans.py`. If `.venv/bin/python` does not exist, initialize a virtual environment and install `requirements.txt`.

---

## Filename convention and global ordering
Each file must be named:
```
i-concept-level-n.yaml
```
Where:
- `i` = global **ID number** (1-indexed, strictly ascending)
- `concept` = a tactic value from the schema enum (use enum order)
- `level`  = a level value from the schema enum (use enum order)
- `n` = **sequence number** (1-indexed), grouping one full pass through all concept/level combinations

**Ordering rule (from lowest to highest):**
1. **ID** ascending
2. **Sequence `n`** ascending (`1, 2, 3, …`)
3. **Concept** in the schema’s enum order
4. **Level** in the schema’s enum order

Let `T = len(tactics)`, `L = len(levels)`, `C = T * L`.
For any ID `i ≥ 1`:
- `n = floor((i - 1) / C) + 1`
- `p = ((i - 1) % C) + 1` (position within sequence `n`)
- `concept_index = floor((p - 1) / L)`
- `level_index  = ((p - 1) % L)`

---

## Starting point detection
1. List files in `./plans/`.
2. Consider only files matching this filename pattern:
   ```
   ^(?<id>\d+)-(?<tactic>[A-Z_]+)-(?<level>LEVEL\d+_[A-Z]+)-(?<n>\d+)\.yaml$
   ```
3. Identify the **highest `id`** among valid filenames; call it `last_id`.
   - If none exist, set `last_id = 0`.
4. The first file in this run has **`id = last_id + 1`**.

Generate **exactly 30 new files**, covering IDs `[last_id + 1 … last_id + 30]`. You may cross sequence boundaries; keep following the global ordering.

**Collision policy**: If a target filename already exists, **skip** it (do not overwrite) and continue incrementing `id` until you have created 30 **new** files.

**Commit policy**: **Do not commit** any changes; only write the files.

---

## Content guidance (defer enforcement to schema)
- Derive `tactic` and `level` values directly from the schema enums (and their order).
- Create varied and realistic plans: vary **formations**, **phase count**, and **phase goals**.
- Use concise US English for objectives and phase names.
- Ensure the **filename’s tactic and level exactly match the document content**.
- Rely on your validator to enforce all structural, field, and value requirements.

---

## Validation (your choice of method)
- Validate each generated document against **`./schemas/plan.json`** using your preferred tools.
- **Only write the file** if it passes validation. If validation fails, fix or skip and continue until 30 valid files are written.

---

## Writing files
- Target path: `./plans/<id>-<tactic>-<level>-<n>.yaml`.
- Do not overwrite existing files.

---

## Post-run summary (optional)
After creating 30 files, print a brief summary to stdout:
- Starting `last_id` and ending `last_id + 30`
- Filenames created
- Next starting ID for the subsequent run

---

**End of instructions.** Follow them exactly.
