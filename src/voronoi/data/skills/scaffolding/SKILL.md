---
name: scaffolding
description: >
  Use for creating small Voronoi investigation scaffolds, task skeletons,
  experiment harness placeholders, manuscript state directories, and reusable
  artifact templates.
user-invocable: true
disable-model-invocation: false
---

# Scaffolding

Use this skill when a worker needs to create the minimal file or directory structure required before real investigation work can start.

## Procedure

1. Identify the artifact contract from task notes: `REQUIRES`, `PRODUCES`, and `GATE`.
2. Create only the directories and stub files needed for the next real step.
3. Put placeholder text in generated files that clearly marks missing content and owner.
4. Do not fabricate results, statistics, citations, or completed analyses.
5. Run the smallest command that proves the scaffold is syntactically usable.

## Output

Report:

- files/directories created
- contracts satisfied
- placeholder content remaining
- verification command and result
