#!/usr/bin/env bash
#
# MarNarMon updater — pull a released version from git and update an
# already-installed host agent (the "engine") and/or the dashboard, on ANY
# server this is deployed to. Server-agnostic: no host, path, domain, or
# reverse-proxy assumptions are baked in.
#
#   Update everything that's installed on this host to the latest release:
#       sudo ./update.sh
#
#   Only the engine, or only the dashboard:
#       sudo ./update.sh --engine
#       ./update.sh --dashboard          # dashboard needs root only if Docker does
#
#   Track the bleeding edge (main) instead of the latest release tag:
#       sudo ./update.sh --edge
#
#   Preview without changing anything:
#       sudo ./update.sh --dry-run
#
# Releases are git tags (vX.Y.Z). With no --ref/--edge the updater picks the
# latest tag, so you get deliberate, published versions rather than whatever is
# on main. It NEVER rewrites config.yml or regenerates the API token, and never
# rewrites your systemd units — it is safe to run on a live, configured server.
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Defaults / constants
# --------------------------------------------------------------------------- #
REPO_URL="https://github.com/heldmar/marnarmon.git"
PREFIX="/opt/marnarmon"               # engine code + venv (matches install.sh)
SERVICE_USER="marnarmon"
API_SERVICE="marnarmon-api.service"
COLLECTOR_SERVICE="marnarmon-collector.service"
DASH_CONTAINER="marnarmon-dashboard"  # conventional container/service name
DASH_IMAGE="marnarmon-dashboard:latest"

# Colours (no-op if not a tty)
if [ -t 1 ]; then
    BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; CYAN="\033[36m"; DIM="\033[2m"; RESET="\033[0m"
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; DIM=""; RESET=""
fi
info()  { printf "${CYAN}==>${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}ok :${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}warn:${RESET} %s\n" "$*" >&2; }
err()   { printf "${RED}err :${RESET} %s\n" "$*" >&2; }
die()   { err "$*"; exit 1; }
step()  { printf "\n${BOLD}%s${RESET}\n" "$*"; }
run()   { # echo + execute, or just echo under --dry-run
    if [ "$DRY_RUN" = 1 ]; then printf "${DIM}dry-run:${RESET} %s\n" "$*"; else eval "$*"; fi
}

# --------------------------------------------------------------------------- #
# Args
# --------------------------------------------------------------------------- #
DO_ENGINE=auto
DO_DASH=auto
REF=""
EDGE=0
DRY_RUN=0
DASH_DIR=""
PORTAINER_WEBHOOK=""

usage() {
    cat <<EOF
MarNarMon updater — update the host agent and/or dashboard from git.

Usage: sudo ./update.sh [options]

Component selection (default: auto-detect and update whatever is installed):
  --engine, --host   Update only the host agent (systemd service).
  --dashboard        Update only the dashboard container.
  --all              Update both (fails if either isn't present).

What to update to:
  --edge             Track the tip of main instead of the latest release tag.
  --ref REF          Update to a specific tag, branch, or commit (e.g. v1.4.0).

Dashboard options:
  --dashboard-dir D  Path to the dashboard's compose checkout (else auto-detect
                     from the running container).
  --portainer-webhook URL
                     If the dashboard is a Portainer git-stack, POST this
                     redeploy webhook instead of touching it directly.

Other:
  --repo URL         Override the git remote (default: $REPO_URL).
  --dry-run          Print what would happen; change nothing.
  -h, --help         This help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --engine|--host) DO_ENGINE=1; [ "$DO_DASH" = auto ] && DO_DASH=0 ;;
        --dashboard)     DO_DASH=1;   [ "$DO_ENGINE" = auto ] && DO_ENGINE=0 ;;
        --all)           DO_ENGINE=1; DO_DASH=1 ;;
        --edge)          EDGE=1 ;;
        --ref)           REF="${2:-}"; shift ;;
        --dashboard-dir) DASH_DIR="${2:-}"; shift ;;
        --portainer-webhook) PORTAINER_WEBHOOK="${2:-}"; shift ;;
        --repo)          REPO_URL="${2:-}"; shift ;;
        --dry-run)       DRY_RUN=1 ;;
        -h|--help)       usage; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

command -v git >/dev/null 2>&1 || die "git is required."

# --------------------------------------------------------------------------- #
# Clone the repo once (small) and resolve the target ref.
# --------------------------------------------------------------------------- #
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
step "Fetching $REPO_URL"
# The clone + checkout are read-only (throwaway temp dir), so we do them even
# under --dry-run — that way the preview resolves the real target version and
# source paths. Only system-mutating steps are gated by run()/--dry-run.
git clone --quiet "$REPO_URL" "$TMP/repo" || die "git clone failed ($REPO_URL)."
SRC="$TMP/repo"

if [ -n "$REF" ]; then
    TARGET="$REF"
elif [ "$EDGE" = 1 ]; then
    TARGET="origin/HEAD"
else
    # Latest release = highest vX.Y.Z tag. Fall back to main if untagged.
    TARGET="$(git -C "$SRC" tag -l 'v*' --sort=-v:refname 2>/dev/null | head -1 || true)"
    if [ -z "$TARGET" ]; then
        warn "No release tags found in the repo — falling back to main (edge)."
        TARGET="origin/HEAD"
    fi
fi
git -C "$SRC" checkout --quiet "$TARGET" 2>/dev/null || die "Ref not found: $TARGET"
RESOLVED="$(git -C "$SRC" describe --tags --always 2>/dev/null || echo "$TARGET")"
ok "Target version: ${BOLD}${RESOLVED}${RESET}"

# --------------------------------------------------------------------------- #
# Auto-detect components if not explicitly chosen.
# --------------------------------------------------------------------------- #
engine_present() { [ -d "$PREFIX/marnarmon" ] && command -v systemctl >/dev/null 2>&1; }
dash_present()   { command -v docker >/dev/null 2>&1 && \
                   docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$DASH_CONTAINER"; }

if [ "$DO_ENGINE" = auto ]; then engine_present && DO_ENGINE=1 || DO_ENGINE=0; fi
if [ "$DO_DASH"   = auto ]; then dash_present   && DO_DASH=1   || DO_DASH=0; fi

if [ "$DO_ENGINE" = 0 ] && [ "$DO_DASH" = 0 ]; then
    die "Nothing to update: no host agent at $PREFIX and no '$DASH_CONTAINER' container found. Use --dashboard-dir or run install.sh for a first-time setup."
fi

# --------------------------------------------------------------------------- #
# Engine (host agent) update
# --------------------------------------------------------------------------- #
update_engine() {
    step "Updating host agent → $RESOLVED"
    engine_present || die "Host agent not found at $PREFIX (run install.sh first)."
    [ "$(id -u)" = 0 ] || die "Updating the host agent needs root: re-run with sudo."
    [ -d "$SRC/host/marnarmon" ] || die "Source is missing host/marnarmon — bad ref?"

    local cur; cur="$(cat "$PREFIX/VERSION" 2>/dev/null || echo 'unknown')"
    info "Installed: $cur  →  Target: $RESOLVED"

    # 1. Snapshot current code for rollback (single backup, overwritten each run).
    run "rm -rf '$PREFIX/marnarmon.bak'"
    run "cp -a '$PREFIX/marnarmon' '$PREFIX/marnarmon.bak'"

    # 2. Replace the package (mirrors install.sh: rm -rf + copy).
    run "rm -rf '$PREFIX/marnarmon'"
    run "cp -a '$SRC/host/marnarmon' '$PREFIX/marnarmon'"

    # 3. Update deps only if requirements.txt changed (updates may add deps).
    if ! diff -q "$SRC/host/requirements.txt" "$PREFIX/requirements.txt" >/dev/null 2>&1; then
        info "requirements.txt changed — updating the virtualenv."
        run "cp -a '$SRC/host/requirements.txt' '$PREFIX/requirements.txt'"
        run "'$PREFIX/venv/bin/pip' install --quiet -r '$PREFIX/requirements.txt'"
    else
        info "Dependencies unchanged — venv left as-is."
    fi

    # 4. Reclaim ownership and record the deployed version.
    run "chown -R '$SERVICE_USER:$SERVICE_USER' '$PREFIX'"
    run "sh -c 'printf %s \"$RESOLVED\" > \"$PREFIX/VERSION\"'"

    # 5. Restart so the process re-reads the new code. Config/token untouched.
    run "systemctl restart '$API_SERVICE'"
    if systemctl list-unit-files 2>/dev/null | grep -q "$COLLECTOR_SERVICE"; then
        run "systemctl restart '$COLLECTOR_SERVICE' || true"
    fi

    if [ "$DRY_RUN" = 0 ]; then
        sleep 1
        if systemctl is-active --quiet "$API_SERVICE"; then
            ok "Host agent updated and API is active."
        else
            err "API did not come back — rolling back would be:"
            err "  sudo rm -rf $PREFIX/marnarmon && sudo mv $PREFIX/marnarmon.bak $PREFIX/marnarmon && sudo systemctl restart $API_SERVICE"
            err "Logs: journalctl -u $API_SERVICE -n 50"
            exit 1
        fi
    fi
    info "Previous code kept at $PREFIX/marnarmon.bak (delete once you've verified)."
}

# --------------------------------------------------------------------------- #
# Dashboard update
# --------------------------------------------------------------------------- #
# Locate the compose working dir of the running dashboard, if any.
detect_dash_dir() {
    command -v docker >/dev/null 2>&1 || return 1
    docker inspect "$DASH_CONTAINER" \
        --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' \
        2>/dev/null | grep -v '^$' || return 1
}
# Is this dashboard a Portainer-OWNED stack that Portainer rebuilds itself?
# Signature: Portainer stores Git/Web-editor stacks under its own data volume at
# `/data/compose/<id>/…`, so the compose working_dir lives there (not on a user
# path we can drive). A local/filesystem stack that points at a user directory
# (e.g. ~/stacks/…) is NOT owned this way and IS updatable via plain compose.
dash_is_portainer() {
    command -v docker >/dev/null 2>&1 || return 1
    local wd; wd="$(detect_dash_dir || true)"
    [ -n "$wd" ] && echo "$wd" | grep -qE '/data/compose/|portainer' && return 0
    docker inspect "$DASH_CONTAINER" --format '{{ json .Config.Labels }}' 2>/dev/null \
        | grep -q 'io.portainer' && return 0
    return 1
}

# If $1 is inside a git checkout of OUR repo, echo that checkout's root and
# return 0; otherwise return 1. Guards against git walking up into an unrelated
# parent repo: we require the checkout's `origin` to point at this project, so we
# never run `git checkout <ref>` against a directory that isn't ours.
_our_checkout_root() {
    local top url
    top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" || return 1
    url="$(git -C "$top" remote get-url origin 2>/dev/null)" || return 1
    local slug="${REPO_URL#*://}"; slug="${slug#*/}"; slug="${slug%.git}"  # heldmar/marnarmon
    case "$url" in *"$slug"*|*"${slug##*/}.git"*) echo "$top"; return 0 ;; esac
    return 1
}

# Move a git checkout to $TARGET (tag/branch/sha). No-op on non-git dirs.
_git_to_target() {
    local d="$1"
    info "Updating source checkout: $d → $RESOLVED"
    run "git -C '$d' fetch --quiet --tags origin"
    run "git -C '$d' checkout --quiet '$TARGET'"
    # On a branch (e.g. --edge → main) fast-forward to the remote tip.
    if git -C "$d" symbolic-ref -q HEAD >/dev/null 2>&1; then
        run "git -C '$d' pull --quiet --ff-only || true"
    fi
}

update_dashboard() {
    step "Updating dashboard → $RESOLVED"
    command -v docker >/dev/null 2>&1 || die "docker not found — can't update the dashboard."

    # --- Portainer git-stack (CICD): Portainer owns the checkout + rebuild. ---
    if dash_is_portainer; then
        if [ -n "$PORTAINER_WEBHOOK" ]; then
            info "Portainer-managed stack — triggering its redeploy webhook."
            run "curl -fsS -X POST '$PORTAINER_WEBHOOK' >/dev/null"
            ok "Redeploy webhook fired. Watch the stack in Portainer."
        else
            warn "This dashboard is a Portainer-managed stack."
            warn "Portainer owns its git checkout and image build, so this updater"
            warn "won't touch it. Update it one of these ways:"
            warn "  • Portainer UI: the stack → 'Pull and redeploy'."
            warn "  • Re-run with --portainer-webhook <URL> to fire its redeploy hook."
        fi
        return 0
    fi

    # --- Compose checkout: pull to the target ref + rebuild in place. ---
    local dir="$DASH_DIR"
    [ -n "$dir" ] || dir="$(detect_dash_dir || true)"
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then
        die "Could not locate the dashboard's compose directory. Pass --dashboard-dir /path/to/checkout (the folder holding docker-compose.yml, on a git checkout of this repo)."
    fi
    info "Dashboard compose dir: $dir"

    local dcfile=""
    for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
        [ -f "$dir/$f" ] && { dcfile="$dir/$f"; break; }
    done
    [ -n "$dcfile" ] || die "No compose file in $dir."

    # docker compose (v2) or docker-compose (v1)
    local DC="docker compose"
    docker compose version >/dev/null 2>&1 || DC="docker-compose"

    # Bring the SOURCE the image builds from up to the target version. A bare
    # `up --build` would otherwise rebuild the OLD code. For each build context
    # docker resolves for this compose file (compose config normalises every
    # build to an absolute context path), update it by its kind:
    #   1. a checkout of THIS repo   -> git checkout the target ref (safe: we
    #      verify the checkout's origin is our repo, never a parent/unrelated one)
    #   2. a plain build dir         -> sync our dashboard/ source into it,
    #      preserving that dir's own compose file and .env
    local updated_any=0 ctx
    while IFS= read -r ctx; do
        [ -n "$ctx" ] || continue
        local top; top="$(_our_checkout_root "$ctx" || true)"
        if [ -n "$top" ]; then
            _git_to_target "$top"; updated_any=1
        elif [ -f "$ctx/Dockerfile" ]; then
            info "Build dir is a plain source copy (not a git checkout of this repo)."
            info "Syncing dashboard source $RESOLVED -> $ctx (its compose file + .env are preserved)."
            if command -v rsync >/dev/null 2>&1; then
                run "rsync -a --exclude='.git' --exclude='docker-compose.y*ml' --exclude='compose.y*ml' --exclude='.env' --exclude='.env.*' '$SRC/dashboard/' '$ctx/'"
            else
                run "sh -c 'cd \"$SRC/dashboard\" && find . -mindepth 1 -maxdepth 1 ! -name \".git\" ! -name \"docker-compose.*\" ! -name \"compose.*\" ! -name \".env*\" -exec cp -a {} \"$ctx/\" \\;'"
            fi
            updated_any=1
        fi
    done < <(cd "$dir" && $DC -f "$dcfile" config 2>/dev/null | awk '$1=="context:"{print $2}' | sort -u)
    [ "$updated_any" = 1 ] || \
        warn "No updatable build source found for $dir — rebuilding from the current on-disk source (it may already be current, use a prebuilt image, or be managed elsewhere)."

    # Preserve the existing compose project name so we recreate the SAME project
    # instead of forking a duplicate (matters for Portainer-created local stacks).
    local proj pflag=""
    proj="$(docker inspect "$DASH_CONTAINER" \
        --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
    [ -n "$proj" ] && pflag="-p '$proj'"

    run "$DC $pflag -f '$dcfile' up -d --build"
    ok "Dashboard rebuilt and redeployed."
}

# --------------------------------------------------------------------------- #
# Go
# --------------------------------------------------------------------------- #
printf "${BOLD}MarNarMon updater${RESET}  (%s)\n" "$([ "$DRY_RUN" = 1 ] && echo 'dry run' || echo 'live')"
info "Plan: engine=$([ "$DO_ENGINE" = 1 ] && echo yes || echo no)  dashboard=$([ "$DO_DASH" = 1 ] && echo yes || echo no)  →  $RESOLVED"

[ "$DO_ENGINE" = 1 ] && update_engine
[ "$DO_DASH"   = 1 ] && update_dashboard

step "Done."
[ "$DRY_RUN" = 1 ] && info "That was a dry run — nothing changed."
exit 0
