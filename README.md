# Galaxy Workflow Validation

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
```
python -m venv planemo
. planemo/bin/activate
pip install planemo
```
Reference: https://planemo.readthedocs.io/en/stable/installation.html

## Dockstore search and download
Use Dockstore cli to search workflow
```
dockstore workflow search --pattern Assembly-decontamination-VGP9
```

This is the output of the dockstore cli
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

REFERENCE
- [IWC workflow](https://github.com/galaxyproject/iwc/blob/main/workflows/README.md)
- [Running Galaxy workflows](https://planemo.readthedocs.io/en/stable/running.html)
- Workflow Example on Dockstore
	- [Assembly-decontamination-VGP9](https://dockstore.org/workflows/github.com/iwc-workflows/Assembly-decontamination-VGP9/main:main?tab=info)
	- [Scaffolding-HiC-VGP8](https://dockstore.org/workflows/github.com/iwc-workflows/Scaffolding-HiC-VGP8/main:main?tab=info)
- [Dockstore documentation](https://docs.dockstore.org/en/latest/launch-with/galaxy-launch-with.html)
- [Browsing Workflow in Dockstore and Galaxy](https://docs.dockstore.org/en/latest/launch-with/galaxy-launch-with.html)