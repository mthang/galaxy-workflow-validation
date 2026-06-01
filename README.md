### galaxy_workflow_checker.py

`galaxy_workflow_checker.py` checks whether all tools required by a Galaxy workflow are installed at the exact version needed, without running the workflow. Works with workflows from WorkflowHub, Dockstore, or a local `.ga` file. Reads Galaxy credentials from a Planemo profile.

### Setup

**Obtain a Galaxy API key**
```
1. Go to https://usegalaxy.org.au/ and log in
2. Click your username (top right) → Preferences → Manage Galaxy API Key
```

**Set up credentials (one-time)**

The checker reads your Galaxy URL and API key from a Planemo profile file at `~/.planemo/profiles/galaxy_profile/planemo_profile_options.json`. You need Planemo installed once to create this file — after that, Planemo does not need to be running to use the checker.

Install Planemo if you don't already have it: https://planemo.readthedocs.io/en/stable/installation.html

Then create the profile:
```
planemo profile_create galaxy_profile \
  --galaxy_url https://usegalaxy.org.au \
  --galaxy_user_key your_galaxy_api_key \
  --engine external_galaxy
```

### Quick start

The most common use is to check a single workflow by its WorkflowHub ID or Dockstore entry. The WorkflowHub ID is the number in the workflow's URL (e.g. `workflowhub.eu/workflows/403` → ID is `403`). The Dockstore entry path is shown in the Dockstore URL for the workflow (e.g. `dockstore.org/workflows/github.com/iwc-workflows/Assembly-decontamination-VGP9/main` → entry is `github.com/iwc-workflows/Assembly-decontamination-VGP9/main`).
```
# WorkflowHub workflow
python galaxy_workflow_checker.py --source workflowhub --id 403

# Dockstore workflow
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main"
```

This checks the latest version and saves two output files: `workflow_check_report.txt` (plain-text table, human-readable) and `workflow_check_report.json` (structured data). It also prints a summary to the terminal. See the Output section for what these files contain.

### Usage

**Check multiple workflows at once** (with optional per-workflow version pinning)
```
python galaxy_workflow_checker.py --source workflowhub --id 403:v2.0.8 875:Version3 876
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-Hifi-only-VGP3/main:v0.3.5" \
            "github.com/iwc-workflows/Scaffolding-HiC-VGP8/main:v1.8"
```

**Search for workflows by keyword** and list matches without checking tools
```
python galaxy_workflow_checker.py --source workflowhub --search "assembly" --list-only
python galaxy_workflow_checker.py --source both --search "decontamination" --list-only
```
Note: `--source dockstore --search` requires the Dockstore CLI — see Dockstore CLI setup below.

**Control which versions are checked**
```
# Latest version only (default — same as omitting --versions)
python galaxy_workflow_checker.py --source workflowhub --id 403

# 3 most recent versions
python galaxy_workflow_checker.py --source workflowhub --id 403 --versions 3

# All versions
python galaxy_workflow_checker.py --source workflowhub --id 403 --versions all

# A specific version
python galaxy_workflow_checker.py --source workflowhub --id 403 --versions v2.0.8

# Two specific versions
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" \
    --versions v1.3,v1.2
```

**Search both registries at once and save to a named output file**
```
python galaxy_workflow_checker.py --source both --search "VGP" --output vgp_report
```
Saves results to `vgp_report.txt` and `vgp_report.json`.

**Check a local `.ga` file** (useful for workflows under development, not yet published, or downloaded for inspection)
```
# Full check (static + tool availability) — requires Galaxy credentials
python galaxy_workflow_checker.py --local-file myworkflow.ga --profile galaxy_profile

# Static checks only — no Galaxy credentials required, useful for quick file validation
python galaxy_workflow_checker.py --local-file myworkflow.ga --static-only

# Set a version label shown in the report (default is "local")
python galaxy_workflow_checker.py --local-file myworkflow.ga --static-only --version-label v1.0.0
```

### All flags

| Flag | Values / default | What it does |
|------|-----------------|--------------|
| `--source` | `workflowhub` / `dockstore` / `both` | Which registry to fetch workflows from |
| `--id` | one or more IDs; optional `:version` suffix | WorkflowHub workflow ID(s) to check (e.g. `403` or `403:v2.0.8`) |
| `--entry` | one or more paths; optional `:version` suffix | Dockstore entry path(s) to check (e.g. `github.com/iwc-workflows/VGP3/main:v0.3.5`) |
| `--search` | keyword string | Search registry for matching workflows (use with `--list-only` to browse, or without to check all matches) |
| `--versions` | `latest` (default) / `all` / `N` / `v1.2,v1.3` | Which versions to check: latest only, all, N most recent, or specific version(s) |
| `--list-only` | flag | List matching workflows without running any checks |
| `--local-file` | file path | Check a local `.ga` file instead of fetching from a registry |
| `--static-only` | flag | Run structural and wiring checks only — skips tool availability check, no Galaxy credentials needed. Only valid with `--local-file`. |
| `--version-label` | string (default: `local`) | Version label shown in the report for a local file run |
| `--output` | base filename (default: `workflow_check_report`) | Base name for output files — creates `<name>.txt` and `<name>.json` |
| `--profile` | profile name (default: `galaxy_profile`) | Planemo profile to read Galaxy URL and API key from (see Setup) |

```
python galaxy_workflow_checker.py --help
```

### Output

Every run (except `--list-only` and `--static-only`) saves two files:
- `<output>.txt` — plain-text summary and results table, readable in any text editor
- `<output>.json` — same data in structured JSON format, useful for scripting or downstream processing

Both files contain the same information. Output also prints to the terminal.

**Example: all workflows ready**
```
Galaxy Workflow Tool Checker (strict version matching)
Generated : 2026-05-13T20:49:35
Galaxy    : https://usegalaxy.org.au

Summary
----------------------------------------
Versions checked              : 11
Ready to run (all exact)      : 11
Blocked by version mismatch   : 0
Blocked by missing tool       : 0

Results
---------------------------------------------------------------------------
Workflow                         Source       Version  Status  Tools  Exact  Mismatch  Missing  Wire
---------------------------------------------------------------------------
Genome-assessment-post-assembly  workflowhub  v2.0.8   ready      13     13         0        0     0
```

**Example: version mismatch**

When tools are installed but at the wrong version, the detail section names the tool and shows what version the workflow needs vs. what Galaxy has:
```
ONT -- Assembly-Flye-AhrensLab  workflowhub  Version 1  version_mismatch  6  2  4  0  0

Blocker / issue detail
----------------------------------------
ONT -- Assembly-Flye-AhrensLab (workflowhub, Version 1) [version_mismatch]
  MISMATCH  toolshed.g2.bx.psu.edu/repos/bgruening/flye/flye
    Galaxy Australia doesn't have the tool version specified in the workflow
    Workflow wants : 2.3.5
    Galaxy Australia has  : 2.3.7, 2.6, 2.8.2+galaxy0 ... (only newer versions available on Galaxy Australia)
```

**Static checks** run automatically on every `.ga` file before the tool check and do not require a Galaxy connection:
- **Structural consistency** — checks required fields are present (`uuid`, `name`, `steps`, `a_galaxy_workflow`), UUID is valid, and every connection between steps points to a step that actually exists. If this fails, further checks are skipped.
- **Wiring gaps** — flags any input slot that is declared but has nothing connected to it. Reported as `WARN` (not a hard failure). Steps with no input connections at all are not flagged — they may use hardcoded parameters or fetch data externally.
- **Subworkflow tools** — if the workflow embeds another workflow as a step, tools inside it are found and checked too, labelled by subworkflow step in the report.

Example — structural error:
```
STRUCTURAL  [FAIL] connection_ref: Step 2 input 'input_file' references non-existent step 9999
```

Example — wiring warning:
```
WIRING  [WARN] Step 2 (fastq_to_fasta) input 'input_file': declared but not connected to any upstream step
```

**Status values** in the results table — most workflows will show `ready` or `version_mismatch`. `structural_error` and `missing_tool` are blockers that will prevent the workflow from running:

| Status | Meaning |
|--------|---------|
| `ready` | All tools installed at the exact version the workflow specifies — safe to run |
| `version_mismatch` | Tools installed but at least one is at the wrong version — may or may not run depending on compatibility |
| `missing_tool` | At least one tool is not installed on Galaxy at all — workflow will fail |
| `structural_error` | The workflow file has a structural problem — tool check skipped, investigate the file |
| `wiring_issues` | Tools are fine but at least one declared input is not connected — informational warning only |
| `no_toolshed_tools` | No ToolShed tools in the workflow — tool check skipped (workflow may use built-in tools only) |

### Older scripts (deprecated)

The following scripts are deprecated and no longer maintained. Use `galaxy_workflow_checker.py` for all new work.

**workflow_inspector.py** — earlier Dockstore checker using Planemo directly
```
python workflow_inspector.py --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" --version "v1.3"
```

**workflowhub_inspector.py** — earlier WorkflowHub checker using BioBlend
```
python workflowhub_inspector.py --search "assembly" --max-workflows 10 --list-only
python workflowhub_inspector.py --id 645 --list-only
python workflowhub_inspector.py --id 645 --version 1
python workflowhub_inspector.py --id 645 --versions-per-workflow all --output vgp_report.json
```

### Dockstore CLI setup (needed for --source dockstore --search only)

Most features use the Dockstore TRS API directly and do not require the Dockstore CLI. The CLI is only needed if you use `--source dockstore --search`. All other Dockstore features (checking by `--entry`, downloading `.ga` files) work without it.

Register a Dockstore account
```
1. Go to https://dockstore.org/register
2. Log in with a GitHub or Google account
```

Obtain a Dockstore token
```
1. Click your username (top right) → Account → Dockstore Account → copy token
```

Install Dockstore CLI (Ubuntu)
```
1. Go to https://dockstore.org/quick-start
2. Install Java 17
   sudo apt-get update -q && sudo apt install -y openjdk-17-jdk
3. Install Docker Engine
   sudo usermod -aG docker $USER
   exec newgrp docker
4. Install Dockstore CLI
   mkdir -p ~/dockstore/bin
   curl -L -o ~/bin/dockstore https://github.com/dockstore/dockstore-cli/releases/download/1.18.0/dockstore
   chmod +x ~/bin/dockstore
   echo 'export PATH=~/bin:$PATH' >> ~/.bashrc
   source ~/.bashrc
5. Add Dockstore token to config
   mkdir -p ~/.dockstore
   printf "token: YOUR_TOKEN\nserver-url: https://dockstore.org/api\n" > ~/.dockstore/config
```

### References
- IWC workflows: [GitHub repo](https://github.com/galaxyproject/iwc) · [README](https://github.com/galaxyproject/iwc/blob/main/workflows/README.md)
- [Running Galaxy workflows with Planemo](https://planemo.readthedocs.io/en/stable/running.html)
- [Dockstore documentation](https://docs.dockstore.org/en/latest/launch-with/galaxy-launch-with.html)
- [WorkflowHub](https://workflowhub.eu)
- GTN: [workflow automation tutorial](https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/workflow-automation/tutorial.html)
- Example workflows on Dockstore: [Assembly-decontamination-VGP9](https://dockstore.org/workflows/github.com/iwc-workflows/Assembly-decontamination-VGP9/main:main?tab=info) · [Scaffolding-HiC-VGP8](https://dockstore.org/workflows/github.com/iwc-workflows/Scaffolding-HiC-VGP8/main:main?tab=info)
- Example workflows on WorkflowHub: [Assembly-decontamination-VGP9](https://workflowhub.eu/workflows/645)
