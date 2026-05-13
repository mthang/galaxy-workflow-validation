# Galaxy Workflow Validation

## Register a Dockstore account
```
1. Go to https://dockstore.org/register
2. Login with either github or google account
```

## Obtain Dockstore Token
```
1. Click on your username at the top right
2. Click on *account* on the drop-down menu
3. Get your Token under *Dockstore Account* 
```
## Environment Setup (Ubuntu)
```
1. Go to https://dockstore.org/quick-start
2. Install Java 17 (This example installs OpenJDK 17)
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
5. Add dockstore token to .dockstore/config
	mkdir -p ~/.dockstore
	printf "token: token_is_availiable_in_your_account_on_dockstore\nserver-url: https://dockstore.org/api\n" > ~/.dockstore/config
```

## Planemo Setup
Planemo is used to test workflow, tools and etc.
```
python -m venv planemo
. planemo/bin/activate
pip install planemo
```
Reference: https://planemo.readthedocs.io/en/stable/installation.html

## Bioblend Setup
Bioblend is used to query and retrieve tools information from Toolshed.
```
pip install bioblend
```
## Dockstore list,  search or download workflow
List all iwc published workflows on dockstore 
```
dockstore workflow search --pattern iwc-workflows
```

Use Dockstore cli to search for particular workflow
```
dockstore workflow search --pattern Assembly-decontamination-VGP9
```

The output of the dockstore cli search with pattern parameter
```
MATCHING WORKFLOWS
---------------------------------------------
NAME                                                          DESCRIPTION   GIT REPO                                                         PUBLISHED
github.com/iwc-workflows/Assembly-decontamination-VGP9/main                 git@github.com:iwc-workflows/Assembly-decontamination-VGP9.git   Yes

```

Query workflow version
```
dockstore workflow info --entry github.com/iwc-workflows/Assembly-decontamination-VGP9/main
```

Get workflow version
```
bash get_wf_version_arg.sh github.com/iwc-workflows/Assembly-decontamination-VGP9/main

Output
main
v1.3
v1.2
v1.1
v1.0
v0.8
v0.7
v0.6
v0.5
v0.4
v0.3
v0.2
v0.1.6
v0.1.4
v0.1.3
v0.1.2
v0.1.1
v0.1
```

## Dockstore download specific version of a workflow
```
dockstore workflow download --entry github.com/iwc-workflows/Assembly-decontamination-VGP9/main:v1.3
```
Note: The Assembly-decontamination-VGP9 (v1.3) workflow on [github](https://github.com/iwc-workflows/Assembly-decontamination-VGP9/blob/v1.3/Assembly-decontamination-VGP9.ga)

## Obtain Galaxy API Key
```
1. Go to https://usegalaxy.org.au/
2. Log into Galaxy
3. Click on your username at the top right
4. Click on *preference*
5. Click on *Manage Galaxy API Key* 
```
## Setup Planemo for testing workflow
```
planemo profile_create galaxy_profile --galaxy_url https://usegalaxy.org.au --galaxy_user_key your_galaxy_api_key --engine external_galaxy
```

## Test the downloaded galaxy workflow file (ga)
This step generates tool_test_output.json and it can use as a missing tool report
```
planemo test Scaffolding-HiC-VGP8.ga --profile galaxy_profile

or

planemo test Assembly-decontamination-VGP9.ga --profile galaxy_profile
```

## Check missing tools
Transform the tool_test_output.json format 
```
cat tool_test_output.json | jq -r '
  .tests[0].data.execution_problem |
  capture("(?<tools>toolshed[^\"]*)").tools |
  split(", ")[] '
```

## Run workflow inspector (Dockstore)
This workflow inspector queries Dockstore and tests the workflow of interest using Planemo
```
python workflow_inspector.py --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" --version "v1.3"
```

## WorkflowHub workflow inspection
Workflows can also be validated from [WorkflowHub](https://workflowhub.eu), which hosts Galaxy workflows independently of Dockstore. The `workflowhub_inspector.py` script queries the WorkflowHub TRS API, downloads `.ga` files, tests them with Planemo, and reports missing tools via BioBlend — no Dockstore CLI required.

No additional installation is needed beyond the Planemo and BioBlend setup above.

List matching workflows without testing
```
python workflowhub_inspector.py --search "assembly" --max-workflows 10 --list-only
```

List all versions of a specific workflow by its WorkflowHub ID
```
python workflowhub_inspector.py --id 645 --list-only
```

Test a specific workflow ID and version
```
python workflowhub_inspector.py --id 645 --version 1
```

Search and test multiple workflows (2 versions each by default)
```
python workflowhub_inspector.py --search "decontamination" --max-workflows 3
```

Test all versions of a workflow
```
python workflowhub_inspector.py --id 645 --versions-per-workflow all --output vgp_report.json
```

Results are saved as both a JSON report and a plain-text table (e.g. `vgp_report.json` and `vgp_report.txt`). The text report lists each workflow version, the number of missing tools, and installation commands for missing tools via ToolShed.

Full list of options
```
python workflowhub_inspector.py --help
```

## Tool availability checker (galaxy_workflow_checker.py)
Check whether all tools required by a workflow are installed in Galaxy Australia,
without needing to run the workflow. Works with workflows from Dockstore, WorkflowHub, or both.
Reads Galaxy credentials automatically from your Planemo profile.

List matching workflows without checking tools
```
python galaxy_workflow_checker.py --source workflowhub --search "assembly" --list-only
python galaxy_workflow_checker.py --source dockstore --search "VGP" --list-only
python galaxy_workflow_checker.py --source both --search "decontamination" --list-only
```

Check tools in the latest version of a specific workflow
```
# By WorkflowHub ID
python galaxy_workflow_checker.py --source workflowhub --id 645

# By Dockstore entry
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main"
```

Control which versions are checked
```
# Latest version only (default)
python galaxy_workflow_checker.py --source workflowhub --id 645 --versions latest

# 3 most recent versions
python galaxy_workflow_checker.py --source workflowhub --id 645 --versions 3

# All versions
python galaxy_workflow_checker.py --source workflowhub --id 645 --versions all

# Specific version(s)
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" \
    --versions v1.3
python galaxy_workflow_checker.py --source dockstore \
    --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" \
    --versions v1.3,v1.2
```

Search both registries at once
```
python galaxy_workflow_checker.py --source both --search "VGP" --versions latest \
    --output vgp_report
```

Output is saved as both `<output>.txt` (plain-text table) and `<output>.json`. The table lists
each workflow, version, number of tools, and how many are missing or mismatched in Galaxy Australia,
with a detail section listing blockers.

**Static checks** — run automatically on every downloaded `.ga` file before the tool check:

- **Structural consistency** — checks the file is a valid Galaxy workflow: required fields present (`uuid`, `name`, `steps`, `a_galaxy_workflow`), UUID is a valid format (not null or malformed), every connection points to a step that actually exists, and `steps` is a dict. If this check fails, the tool check is skipped.
- **Wiring gaps** — flags any tool step that has no input connections at all. Reported as `WARN` (not `FAIL`) because without querying the tool XML we can't confirm whether those inputs are required.
- **Subworkflow tools** — if the workflow embeds subworkflows, their tools are found too and labelled by subworkflow step name in the report.

**Version mismatch direction** — when a tool version does not match, the report notes whether the installed version is older or newer than what the workflow requires, e.g. `MISMATCH  (installed older)`.

Example output for a workflow with a structural error:
```
STRUCTURAL  [FAIL] connection_ref: Step 2 input 'input_file' references non-existent step 9999
```

Example output for a wiring warning:
```
WIRING      [WARN] Step 2 (fastq_to_fasta): no input connections — relies entirely on hardcoded parameters or has no inputs
```

Example output for a version mismatch:
```
MISMATCH  (installed older)  toolshed.g2.bx.psu.edu/repos/devteam/fastq_groomer/fastq_groomer
  wants : 1.1.5+galaxy2
  avail : 1.0.4+galaxy0, 1.1.1+galaxy1
```

The results table includes a `Wire` column showing the count of wiring warnings per workflow version.

Check a local `.ga` file directly (no registry fetch needed)
```
# Static checks only — no Galaxy credentials required
python galaxy_workflow_checker.py --local-file myworkflow.ga --static-only

# Full check (static + tool availability) — requires Galaxy credentials
python galaxy_workflow_checker.py --local-file myworkflow.ga --profile galaxy_profile

# Set a version label in the report (default is "local")
python galaxy_workflow_checker.py --local-file myworkflow.ga --static-only --version-label v1.0.0
```

Full list of options
```
python galaxy_workflow_checker.py --help
```

REFERENCE
- IWC workflow
	- [Github repo](https://github.com/galaxyproject/iwc)
	- [README](https://github.com/galaxyproject/iwc/blob/main/workflows/README.md)
- [Running Galaxy workflows](https://planemo.readthedocs.io/en/stable/running.html)
- Workflow Example on Dockstore
	- [Assembly-decontamination-VGP9](https://dockstore.org/workflows/github.com/iwc-workflows/Assembly-decontamination-VGP9/main:main?tab=info)
	- [Scaffolding-HiC-VGP8](https://dockstore.org/workflows/github.com/iwc-workflows/Scaffolding-HiC-VGP8/main:main?tab=info)
- Workflow Example on WorkflowHub
	- [Assembly-decontamination-VGP9](https://workflowhub.eu/workflows/645)
- [Dockstore documentation](https://docs.dockstore.org/en/latest/launch-with/galaxy-launch-with.html)
- [Browsing Workflow in Dockstore and Galaxy](https://docs.dockstore.org/en/latest/launch-with/galaxy-launch-with.html)
- [WorkflowHub](https://workflowhub.eu)
- GTN material
	- [workflow automation](https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/workflow-automation/tutorial.html)