# Maintaining the toolkit

The profile badges come from `data/toolkit.json`. Each entry has a label, documentation link, group, and public repository evidence. Brand icons are stored locally in `assets/toolkit/icons`; their source and license are in `assets/toolkit/NOTICE.txt`.

The inventory is curated. A dependency shows that a project uses a tool; it does not establish expertise, ownership, or how much code someone wrote. The badge section includes no proficiency scores, rankings, or language percentages.

## Update the profile

1. Review a tool's use and add or edit its entry in `data/toolkit.json`.
2. Add a local source icon if needed, or leave `icon` as `null` for a labeled badge.
3. Run `python scripts/update-toolkit.py`.
4. Review the README and generated SVG files before committing.

The script only updates the toolkit marker block and badges. It preserves the introduction, projects, header, and personal section.

## Check for changes

```sh
python scripts/update-toolkit.py --check
python scripts/update-toolkit.py --audit --report toolkit-audit.json
```

The audit reads the current default branches of the configured public repositories. It reports existing entries that need review, unavailable sources, and a short list of potentially relevant dependencies. It does not add tools, change the README, commit, push, or create issues.

The workflow runs this audit monthly and on manual dispatch, with read-only repository permissions. Its results appear in the Actions run summary. Pull requests only check that the generated files match the inventory. Scheduled runs use the workflow on the default branch.

The audit can use an existing GitHub CLI login, or `GH_TOKEN` / `GITHUB_TOKEN` when provided. It does not require a separate personal access token for public sources. Private repositories and career notes are not inputs to the scheduled audit.
