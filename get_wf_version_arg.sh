#!/bin/bash

# Script: get_workflow_versions.sh
# Usage: ./get_workflow_versions.sh github.com/iwc-workflows/Assembly-decontamination-VGP9/main

WORKFLOW_PATH="$1"

if [ -z "$WORKFLOW_PATH" ]; then
    echo "Error: Please provide a workflow path"
    echo "Usage: $0 <workflow_path>"
    echo "Example: $0 github.com/iwc-workflows/Assembly-decontamination-VGP9/main"
    exit 1
fi

versions=$(dockstore workflow info --entry "$WORKFLOW_PATH" |
  sed -n '/WORKFLOW VERSIONS/{n; s/^[[:space:]]*//; p}' |
  tr -d ' ' |
  tr ',' '\n')

echo "Workflow versions for $WORKFLOW_PATH:"
echo "$versions"
