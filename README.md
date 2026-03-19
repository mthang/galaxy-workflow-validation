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

## Dockstore download specific version of a workflow
```
dockstore workflow download --entry github.com/iwc-workflows/Assembly-decontamination-VGP9/main:v1.2
```

## Setup Planemo for testing workflow
```
planemo profile_create galaxy_profile --galaxy_url https://usegalaxy.org.au --galaxy_user_key your_galaxy_api_key --engine external_galaxy
```

## Test the downloaded galaxy workflow file (ga)
This step generates tool_test_output.json and it can use as a missing tool report
```
planemo test Scaffolding-HiC-VGP8.ga --profile galaxy_profile
```

## Check missing tools
Transform the tool_test_output.json format 
```
cat tool_test_output.json | jq -r '
  .tests[0].data.execution_problem |
  capture("(?<tools>toolshed[^\"]*)").tools |
  split(", ")[] '
```