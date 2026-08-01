# Verification thinking loops

HivePack treats quality as a series of adversarial gates. Every automated check prints a **THINK** line stating what failure mode it is hunting.

## Gates (`hivepack verify`)

| # | Gate | Pass criteria | Adversarial question |
|---|------|---------------|----------------------|
| 1 | doctor | Python + pack on disk | Can we even run? |
| 2 | hivepack_validate | 0 errors | Would Beekeep/Buzz reject secrets, missing skills, blank prompts? |
| 3 | export_snapshots | 4 files, `memory.level=none`, empty entries | Could a shared snapshot leak memory or keys? |
| 4 | buzz pack validate | official CLI exit 0 | Does Block's own validator agree? |
| 5 | buzz pack inspect | all 4 persona names | Did resolve/merge drop an agent? |
| 6 | pytest | all green | Did we regress parsers? |

## Per-validate THINK stages

1. **layout** — plugin.json, path traversal, skill files  
2. **personas** — identity fields, uniqueness, secret regex  
3. **team-coherence** — role boundaries (reviewer doesn't implement, etc.)  
4. **distribution-safety** — snapshot hygiene  

## Human gates (not automated)

- Import preview in Buzz shows no memory/secrets  
- Demo recorded on a **test** community  
- Harnesses attached before claiming "it works"  
- No prod deploy autonomy without human 👍  

If any automated gate fails: **do not ship**. If a human gate fails: **do not post the demo**.
