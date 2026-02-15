#!/bin/bash
# =============================================================================
# restore-failed.sh — Restore false-positive FAILED pages
# =============================================================================
#
# Scans all studies/*/300/FAILED/ for pages marked with specific error reasons
# (default: empty_response) and restores them as empty HTML placeholders
# so the next crawl run will retry them.
#
# USAGE:
#   ./scripts/restore-failed.sh                    # dry-run (show what would be restored)
#   ./scripts/restore-failed.sh --apply            # actually restore
#   ./scripts/restore-failed.sh --reason=empty_response --apply
#   ./scripts/restore-failed.sh --reason=all --apply   # restore ALL failed (nuclear)
#
# WHAT IT DOES:
#   1. Scans studies/*/300/FAILED/ for files matching the reason
#   2. Recreates empty html placeholder: touch studies/<domain>/300/html/<sha>.html
#   3. Moves FAILED marker to $BASE/removed/
#
# =============================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
STUDIES="$BASE/studies"
REMOVED="$BASE/removed"
REASON="empty_response"
APPLY=false

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --apply)
            APPLY=true
            ;;
        --reason=*)
            REASON="${arg#--reason=}"
            ;;
        --help|-h)
            echo "Usage: $0 [--reason=empty_response|all] [--apply]"
            echo ""
            echo "Options:"
            echo "  --reason=REASON   Filter by FAILED reason (default: empty_response)"
            echo "  --reason=all      Match ALL failed files regardless of reason"
            echo "  --apply           Actually restore (default: dry-run)"
            echo ""
            echo "Known reasons: empty_response, 404_not_found, 403_forbidden,"
            echo "  500_server_error, 502_bad_gateway, 503_unavailable,"
            echo "  skipped_binary, redirect_external, download_error"
            exit 0
            ;;
    esac
done

mkdir -p "$REMOVED"

echo "=== restore-failed.sh ==="
echo "  Studies:  $STUDIES"
echo "  Reason:   $REASON"
echo "  Mode:     $([ "$APPLY" = true ] && echo 'APPLY' || echo 'DRY-RUN')"
echo ""

total_found=0
total_restored=0
timestamp=$(date +%Y%m%d_%H%M%S)

for study_dir in "$STUDIES"/*/300; do
    [ -d "$study_dir/FAILED" ] || continue

    domain=$(echo "$study_dir" | sed "s|$STUDIES/||;s|/300||")
    failed_dir="$study_dir/FAILED"
    html_dir="$study_dir/html"

    found=0
    restored=0

    for failed_file in "$failed_dir"/*; do
        [ -f "$failed_file" ] || continue

        sha=$(basename "$failed_file")

        # Match reason
        if [ "$REASON" != "all" ]; then
            # Check file content for reason pattern
            if ! grep -q "$REASON" "$failed_file" 2>/dev/null; then
                # Also match empty files (0 bytes = old bridge errors with no reason)
                if [ -s "$failed_file" ]; then
                    continue
                fi
                # Empty file = unknown reason, only match if reason is empty_response
                if [ "$REASON" != "empty_response" ]; then
                    continue
                fi
            fi
        fi

        found=$((found + 1))
        total_found=$((total_found + 1))

        # Get URL from INDEX or from FAILED file content
        url=""
        if [ -f "$study_dir/INDEX/$sha" ]; then
            url=$(cat "$study_dir/INDEX/$sha" 2>/dev/null)
        elif [ -s "$failed_file" ]; then
            url=$(cut -d'|' -f1 < "$failed_file" 2>/dev/null)
        fi

        if [ "$APPLY" = true ]; then
            # Recreate empty HTML placeholder
            mkdir -p "$html_dir"
            touch "$html_dir/$sha.html"

            # Ensure INDEX entry exists
            if [ -n "$url" ] && [ ! -f "$study_dir/INDEX/$sha" ]; then
                mkdir -p "$study_dir/INDEX"
                echo "$url" > "$study_dir/INDEX/$sha"
            fi

            # Move FAILED to removed
            mv "$failed_file" "$REMOVED/${timestamp}_FAILED_${domain}_${sha}"

            restored=$((restored + 1))
            total_restored=$((total_restored + 1))
        fi
    done

    if [ "$found" -gt 0 ]; then
        if [ "$APPLY" = true ]; then
            echo "  $domain: $restored/$found restored"
        else
            echo "  $domain: $found to restore"
        fi
    fi
done

echo ""
if [ "$APPLY" = true ]; then
    echo "DONE: $total_restored/$total_found pages restored"
    echo "  HTML placeholders recreated (size 0 = pending download)"
    echo "  FAILED markers moved to $REMOVED/"
    echo "  Run crawl to retry these pages"
else
    echo "FOUND: $total_found pages to restore"
    echo "  Run with --apply to restore them"
fi
