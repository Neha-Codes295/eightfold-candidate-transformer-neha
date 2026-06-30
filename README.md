# candidate-transformer

Merges candidate data from multiple sources (CSV, ATS JSON, GitHub) into one canonical JSON profile per person.

## Setup

Python 3.9+ required. Only one external dependency:

```bash
pip install requests
```

No virtual environment required beyond that. Clone the repo and run from its root.

## Run Commands

### Full canonical output (all fields, confidence, provenance)
```bash
python main.py \
  --csv sample_inputs/candidates.csv \
  --ats sample_inputs/ats.json \
  --github torvalds \
  --github octocat \
  --output output.json
```

### With custom config projection (subset of fields)
```bash
python main.py \
  --csv sample_inputs/candidates.csv \
  --ats sample_inputs/ats.json \
  --config config.json \
  --output output.json
```

### CSV + ATS only (no GitHub calls)
```bash
python main.py \
  --csv sample_inputs/candidates.csv \
  --ats sample_inputs/ats.json \
  --output output.json
```

All flags are repeatable: `--csv a.csv --csv b.csv --github user1 --github user2`.

## Example Output

### Full canonical schema (no config)

```json
{
  "candidate_id": "fe539fd784f1",
  "full_name": "Priya Sharma",
  "emails": ["priya.sharma@email.com"],
  "phones": ["+919876543210"],
  "location": { "city": "Bengaluru", "region": null, "country": "IN" },
  "links": {
    "linkedin": "https://linkedin.com/in/priya-sharma",
    "github": null,
    "portfolio": null,
    "other": []
  },
  "headline": "Full-stack engineer with 4 years in enterprise software",
  "years_experience": 4.0,
  "skills": [
    { "name": "aws",    "confidence": 1.0, "sources": ["ats"] },
    { "name": "docker", "confidence": 1.0, "sources": ["ats"] },
    { "name": "java",   "confidence": 1.0, "sources": ["ats"] },
    { "name": "python", "confidence": 1.0, "sources": ["ats"] }
  ],
  "experience": [
    { "company": "Infosys", "title": "Software Engineer", "start": null, "end": null, "summary": null }
  ],
  "education": [],
  "provenance": [
    { "field": "full_name", "source": "csv", "method": "direct" },
    { "field": "full_name", "source": "ats", "method": "mapped" }
  ],
  "overall_confidence": 0.9375
}
```

### Projected output (with config.json)

```json
{
  "full_name": "Priya Sharma",
  "primary_email": "priya.sharma@email.com",
  "phone": "+919876543210",
  "skills": ["aws", "docker", "java", "python"],
  "overall_confidence": 0.9375
}
```

## Pipeline Architecture

```
Raw Sources
  ├── CSV  ──────────────────┐
  ├── ATS JSON (mapped) ─────┤  extract.py
  └── GitHub API ────────────┘
          │
          ▼
    normalize.py       phones → E.164, dates → YYYY-MM, skills → lowercase deduped
          │
          ▼
    merge.py           group by email (fallback: name), collapse per source priority
          │
          ▼
    confidence.py      per-field + overall confidence scores
          │
          ▼
    project.py         apply config: select/rename/remap fields, dot+array paths
          │
          ▼
    validate.py        schema check, fill missing keys with null, warn on mismatches
          │
          ▼
    output.json
```

Each stage lives in `pipeline/<stage>.py`. Models (dataclasses) live in `models/candidate.py`.

## How Merging Works

- **Primary key**: email. Any shared email address across records groups them as the same person.
- **Fallback key**: normalized full name (lowercased, whitespace-collapsed), used when no email is present.
- **Scalar conflicts** (name, phone, headline): source priority CSV > ATS > GitHub. Most complete/non-null value wins.
- **Skills/headline**: union across all sources — no data is thrown away.
- **candidate_id**: deterministic SHA-1 of the primary email (or name if no email). Same input → same ID always.

## Confidence Scoring

- **Per-field confidence** = (sources agreeing on value) / (sources providing field)
  - For list fields (emails, skills), "agreeing" means any overlap between the sets.
- **Per-skill confidence** = (sources that include this skill) / (sources that provided any skills)
- **overall_confidence** = average of per-field confidences

A candidate only seen in one source scores 1.0 (no conflicting data, not penalized for being unique).

## Config Projection

`config.json` selects, renames, and remaps fields at runtime without touching the pipeline.

```json
{
  "fields": [
    { "path": "full_name",     "from": "full_name" },
    { "path": "primary_email", "from": "emails[0]" },
    { "path": "phone",         "from": "phones[0]",     "normalize": "e164" },
    { "path": "skills",        "from": "skills[].name", "normalize": "lowercase" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

**Path syntax:**
- `emails[0]` — first element of an array
- `skills[].name` — pluck `name` from every element of `skills`, returning a flat list
- `links.github` — nested object access

**`on_missing` values:**
- `"null"` (default) — include the field with value `null`
- `"omit"` — exclude the field from output entirely
- `"error"` — raise a clear exception and halt

**`normalize` overrides:**
- `"e164"` — format phone numbers to E.164
- `"lowercase"` — lowercase all string values
- `"date"` — normalize date strings to YYYY-MM

If `--config` is omitted, the full canonical schema is output with both `provenance` and `overall_confidence` included.

## ATS Field Mapping

The ATS extractor maps these non-canonical field names to canonical ones:

| ATS field | Canonical |
|---|---|
| `candidate_name` | `full_name` |
| `contact_email` | `emails` |
| `phone_number` | `phones` |
| `employer` / `current_employer` | `experience[0].company` |
| `role` / `job_title` / `current_role` | `experience[0].title` |
| `summary` / `bio` | `headline` |
| `skills` / `tags` | `skills[]` |
| `experience_years` / `years_of_experience` | `years_experience` |
| `linkedin_url` | `links.linkedin` |
| `github_url` | `links.github` |

## Error Handling

| Error condition | Behavior |
|---|---|
| CSV file not found | Warning printed; source skipped; pipeline continues |
| ATS JSON malformed | Warning printed; source skipped; pipeline continues |
| GitHub 404 (user not found) | Warning printed; source skipped |
| GitHub 403 (rate limit) | Warning printed; source skipped |
| GitHub network timeout | Warning printed; source skipped |
| `requests` not installed | Warning printed; GitHub source skipped |
| Field missing with `on_missing=error` | Clear exception raised with field name and path |
| Config file not found/malformed | Warning; falls back to full canonical output |

Warnings are collected and printed to stderr after all output is written.

## Assumptions

1. **Country code default**: Phone numbers without an explicit country code (`+XX` prefix) are assumed to be Indian numbers and normalized to `+91XXXXXXXXXX`.
2. **Email as primary merge key**: Two records with any shared email address are considered the same candidate.
3. **Determinism**: Candidate IDs are SHA-1 hashes of the primary email. Skill/source lists are sorted. Output list is sorted by `candidate_id`.
4. **GitHub languages**: The `language` field on each repo (GitHub's detected primary language) is used as a skill proxy. Detailed per-file language stats are not fetched to avoid excessive API calls.
5. **ATS schema flexibility**: The ATS mapper handles both `string` and `list` values for email, phone, and skills fields.
6. **Headline preference**: When multiple sources provide headlines, the longest (most descriptive) is used.
7. **No data invention**: Fields not present in any source remain `null`. The pipeline never guesses or fills in values.

## Descoped Items

- **LinkedIn scraping**: LinkedIn blocks API access; would require a paid partner API or scraping (ToS violation). Descoped — LinkedIn URLs are stored as-is in `links.linkedin` if provided by ATS.
- **Resume/PDF parsing**: Requires heavy dependencies (pdfminer, spaCy, etc.). Descoped to keep the tool dependency-free.
- **Automated tests**: Unit + integration tests are the natural next step; descoped per assignment instructions.
- **Authentication**: GitHub API calls are unauthenticated (60 req/hour rate limit). Swap in a `GITHUB_TOKEN` env var in `extract.py` for higher limits.
- **Education extraction**: Education data requires resume parsing or structured ATS fields; current ATS sample doesn't include it.
- **Fuzzy name matching**: Current fallback uses exact normalized name match. Fuzzy matching (e.g. "Priya S." vs "Priya Sharma") is descoped.

## Swapping In a Different Config

Create any JSON file following the config schema above and pass it via `--config`:

```bash
python main.py --csv data.csv --config my_config.json --output out.json
```

The config is applied as a pure post-processing projection — the canonical merge always runs first, so switching configs never re-parses source data.
