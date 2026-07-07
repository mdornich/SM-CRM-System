#!/usr/bin/env zsh
set -euo pipefail

REPO_DIR="/Users/mitchdornich/Documents/GitHub/SM-CRM-System"
cd "$REPO_DIR"

if [[ "${1:-}" != "--yes" ]]; then
  cat <<'EOF'
This moves local generated state out of the way:
  output/relationship_intel.db
  output/mock_crm/
  output/logs/

It does not delete or modify Twenty records. Remove sample records from Twenty UI
manually when moving from POC data to real acceptance data.

Run again with --yes to create a timestamped backup under output/reset-backups/.
EOF
  exit 2
fi

stamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="output/reset-backups/${stamp}"
mkdir -p "$backup_dir"

for path in output/relationship_intel.db output/mock_crm output/logs; do
  if [[ -e "$path" ]]; then
    mv "$path" "$backup_dir/"
  fi
done

mkdir -p output
touch output/.gitkeep

echo "Moved local generated state to ${backup_dir}"
