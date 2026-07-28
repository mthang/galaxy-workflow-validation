Below is the updated `README.md` test‑case document, with a new **Setup** section and the command examples updated to use the refactored `gwc` tool.

---

# Galaxy Workflow Checker (gwc) – Test Cases

## Setup

### 1. Installation

Install the `gwc` package in development mode:

```bash
# Clone the repository (if not already done)
git clone https://github.com/mthang/galaxy-workflow-validation.git
cd galaxy-workflow-validation

# Install dependencies and the package
pip install -e .
```

This installs all required dependencies (`PyYAML`, `bioblend`, `requests`, `tabulate`) and makes the `gwc` command available.

### 2. Dependencies

The tool requires:

- Python 3.7 or later
- `PyYAML` – for reading configuration files
- `bioblend` – for interacting with Galaxy instances
- `requests` – for WorkflowHub REST API calls
- `tabulate` – for pretty‑table output

These are automatically installed when you run `pip install -e .`.

### 3. Galaxy API Key (for private instances)

If you are checking workflows against a **private** Galaxy instance, you need an API key.

1. Log in to your Galaxy instance (e.g., `https://usegalaxy.org.au`).
2. Click your username (top right) → **Preferences** → **Manage Galaxy API Key**.
3. Copy your API key.

### 4. Planemo Profile (recommended)

The checker reads Galaxy credentials from a Planemo profile. This is the recommended way to store your Galaxy URL and API key.

Install Planemo if you don't already have it:  
https://planemo.readthedocs.io/en/stable/installation.html

Create the profile (one‑time setup):

```bash
planemo profile_create galaxy_profile \
    --galaxy_url https://usegalaxy.org.au \
    --galaxy_user_key your_galaxy_api_key \
    --engine external_galaxy
```

After this, the checker will use `~/.planemo/profiles/galaxy_profile/planemo_profile_options.json` automatically.

### 5. WorkflowHub API Token (for `hub` commands)

To use the `gwc hub` subcommand (metadata listing, RO‑Crate download), you need a WorkflowHub API token.

1. Log in to [WorkflowHub](https://workflowhub.eu).
2. Go to your **Account Settings** → **API Tokens**.
3. Generate a new token and save it.
4. Store the token in a file (default: `~/.workflowhub/api_token.txt`):

```bash
mkdir -p ~/.workflowhub
echo "your_token_here" > ~/.workflowhub/api_token.txt
```

### 6. Configuration File (optional)

You can create a `config.yaml` file to override default URLs and behaviour. A sample configuration:

```yaml
workflowhub:
  trs_base: "https://workflowhub.eu/ga4gh/trs/v2"
  base_url: "https://workflowhub.eu"

dockstore:
  base_url: "https://dockstore.org"
  trs_base: "https://dockstore.org/api/ga4gh/trs/v2"

galaxy_instances:
  friendly_names:
    "usegalaxy.org.au": "Galaxy Australia"
    "usegalaxy.org": "Galaxy Main"
    "usegalaxy.eu": "Galaxy Europe"

defaults:
  profile_name: "galaxy_profile"
  workspace_dir: "./workflow_workspace"
  output_base: "workflow_check_report"
  max_workflows: 10
  max_workers: 5

workflowhub_rest:
  base_url: "https://workflowhub.eu"
  token_file: "~/.workflowhub/api_token.txt"
  projects: ["30", "54"]

skip_step_types:
  - "data_input"
  - "data_collection_input"
  - "parameter_input"
  - "pause"
```

Pass it with `--config` or place it in the working directory.

---

## Quick Start

The most common use is to check a single workflow by its WorkflowHub ID or Dockstore entry.

```bash
# WorkflowHub workflow
gwc check 403

# Dockstore workflow
gwc check github.com/iwc-workflows/Assembly-decontamination-VGP9/main
```

This checks the latest version and saves two output files: `workflow_check_report.txt` (plain‑text table) and `workflow_check_report.json` (structured data). It also prints a summary to the terminal.

---

## Test Cases

### 1. `check` Command (Workflow Validation)

#### 1.1 Basic Workflow Checks

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| C‑01 | Check latest version of a WorkflowHub workflow | `gwc check 645` | Downloads `.ga`, checks tools, produces `txt` report with status `ready` or issues. |
| C‑02 | Check specific version of WorkflowHub workflow | `gwc check 403 --version v2.0.8` | Uses exact version; if not found, reports `version_not_found`. |
| C‑03 | Check Dockstore workflow (latest) | `gwc check github.com/iwc-workflows/Assembly/main` | Resolves entry, downloads, checks. |
| C‑04 | Check Dockstore workflow with specific version | `gwc check github.com/iwc-workflows/Assembly/main --version v0.3.5` | Uses exact version. |
| C‑05 | Check local `.ga` file | `gwc check my_workflow.ga` | Runs static + tool checks against default Galaxy. |
| C‑06 | Check local file with `--static-only` | `gwc check my_workflow.ga --static-only` | Skips tool checks; only structural/wiring. |

#### 1.2 Batch / CSV Mode

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| C‑07 | Process CSV with valid entries | `gwc check --csv workflows.csv` | Checks all rows, produces combined report. |
| C‑08 | CSV with duplicate workflow IDs but different versions | `gwc check --csv duplicate.csv` | Each row is checked independently; exact version matching; `version_not_found` if no match. |
| C‑09 | CSV with invalid registry | `gwc check --csv invalid_registry.csv` | Skips row with warning, continues. |
| C‑10 | CSV with missing columns | `gwc check --csv missing_col.csv` | Exits with clear error message. |

#### 1.3 Search & Registry Selection

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| C‑11 | Search WorkflowHub | `gwc check --search assembly --source workflowhub` | Lists workflows, checks latest versions of each. |
| C‑12 | Search Dockstore | `gwc check --search assembly --source dockstore` | Lists and checks. |
| C‑13 | Search both registries | `gwc check --search VGP --source both` | Combines results from both. |
| C‑14 | Use `--id` with version pin | `gwc check --id 403:v2.0.8 875:Version3` | Each ID uses its pinned version. |

#### 1.4 Parallel & Performance

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| C‑15 | Parallel processing (CSV) | `gwc check --csv big.csv --parallel --max-workers 10` | Speeds up; all workflows processed. |
| C‑16 | Disable cache | `gwc check 645 --no-cache` | Re‑fetches Galaxy tool list. |

#### 1.5 Output Formats & Extra Reports

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| C‑17 | Generate HTML report | `gwc check 645 --format html` | Creates `.html` file. |
| C‑18 | Export tool issues CSV | `gwc check 645 --export-tool-issues-csv` | Creates `_tool_issues.csv`. |
| C‑19 | Generate install script | `gwc check 645 --export-install-script` | Creates `.sh` script for missing tools. |
| C‑20 | Compare workflows (batch) | `gwc check --csv multi.csv --compare-workflows` | Produces `_comparison.json`. |

---

### 2. `list` Command (Galaxy Published Workflows)

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| L‑01 | List all published workflows (default Galaxy) | `gwc list` | Fetches all (no limit) and displays table. |
| L‑02 | List with limit | `gwc list --limit 20` | Shows only first 20. |
| L‑03 | List with `--stats` | `gwc list --stats` | Shows summary (total, top tags, oldest/newest). |
| L‑04 | Search by name | `gwc list --search assembly` | Filters workflows. |
| L‑05 | Filter by tag | `gwc list --tag workflowhub` | Shows only tagged. |
| L‑06 | Export to CSV | `gwc list --output workflows.csv` | Creates CSV. |
| L‑07 | Export to TSV | `gwc list --output workflows.tsv` | Creates TSV. |
| L‑08 | Target different Galaxy instance | `gwc list --galaxy-url https://usegalaxy.eu` | Works for any public instance. |
| L‑09 | Use API key (private instance) | `gwc list --galaxy-url https://private.instance --api-key KEY` | Authenticates and lists. |

---

### 3. `hub` Command (WorkflowHub REST Metadata)

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| H‑01 | List workflows contributed by user | `gwc hub list-mine` | Requires valid token file; lists workflows. |
| H‑02 | List workflows in a project | `gwc hub list-project 30` | Shows workflows with creators/affiliations. |
| H‑03 | Filter project workflows by class | `gwc hub list-project 30 --class galaxy` | Only Galaxy workflows. |
| H‑04 | Get detailed metadata for a workflow | `gwc hub get 403` | Displays key‑value table. |
| H‑05 | List related items | `gwc hub list-related 403` | Shows data files, publications, etc. |
| H‑06 | Download RO‑Crate | `gwc hub download-rocrate 403 --output-dir ./downloads` | Saves zip file. |
| H‑07 | Output formats (table, tsv, json) | `gwc hub get 403 --format json` | Returns JSON. |

---

### 4. Error Handling & Edge Cases

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| E‑01 | No token file for `hub` | Prints error and exits. |
| E‑02 | Invalid workflow ID for `check` | Reports `workflow not found` or continues. |
| E‑03 | Missing required arguments for `check` | Parser shows usage and exits. |
| E‑04 | Unsupported file format for `--csv` | Graceful error. |
| E‑05 | Network timeout (Galaxy API) | Handles exception, prints error. |
| E‑06 | Malformed `.ga` file | Structural checker flags errors; report shows `structural_error`. |

---

### 5. Regression Tests (Legacy Support)

| Test ID | Description | Command Example | Expected Outcome |
|---------|-------------|-----------------|------------------|
| R‑01 | Legacy flat style for `check` | `gwc --csv workflows.csv --output report` | Works same as `gwc check --csv ...`. |
| R‑02 | Legacy `--list-published` (maps to `list`) | `gwc --list-published --galaxy-url https://usegalaxy.org.au` | Works (if supported in parser). |
| R‑03 | Old `--versions` flag | `gwc check --versions 3` | Processes N most recent versions. |

---

### 6. Configuration & Environment

| Test ID | Description | Command | Expected Outcome |
|---------|-------------|---------|------------------|
| ENV‑01 | Use config file | `gwc check 645 --config my_config.yaml` | Overrides defaults. |
| ENV‑02 | Set `GWC_MAX_WORKERS` | `GWC_MAX_WORKERS=10 gwc check --csv big.csv` | Uses env var. |
| ENV‑03 | Missing config file | `gwc check 645 --config nonexistent.yaml` | Reports file not found. |
