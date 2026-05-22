#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[kinatio-install] %s\n' "$*"
}

fail() {
  printf '[kinatio-install] error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./install.sh [--dev] [--help]

Bootstrap Kinatio into a local .venv for supported Linux distributions.

Options:
  --dev      Install editable package with development extras.
  -h, --help Show this help text.
EOF
}

python_meets_minimum() {
  local candidate="$1"
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

python_supports_pip() {
  local candidate="$1"
  "$candidate" -m pip --version >/dev/null 2>&1
}

python_supports_venv() {
  local candidate="$1"
  "$candidate" -c 'import venv' >/dev/null 2>&1
}

python_version() {
  local candidate="$1"
  "$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
}

pick_python() {
  local candidate
  for candidate in python3 python3.12 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_meets_minimum "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

detect_family() {
  if [[ ! -r /etc/os-release ]]; then
    fail 'missing /etc/os-release; this installer only supports Linux distributions with os-release metadata'
  fi

  # shellcheck disable=SC1091
  source /etc/os-release

  local id="${ID:-}"
  local like="${ID_LIKE:-}"
  local fingerprint=" ${id} ${like} "

  case "$fingerprint" in
    *" fedora "*|*" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*)
      printf '%s\n' 'dnf'
      ;;
    *" arch "*|*" archlinux "*|*" manjaro "*|*" endeavouros "*)
      printf '%s\n' 'pacman'
      ;;
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*|*" raspbian "*)
      if command -v apt-get >/dev/null 2>&1; then
        printf '%s\n' 'apt-get'
      elif command -v apt >/dev/null 2>&1; then
        printf '%s\n' 'apt'
      else
        fail 'detected Debian-family Linux but neither apt-get nor apt is available'
      fi
      ;;
    *)
      if command -v dnf >/dev/null 2>&1; then
        printf '%s\n' 'dnf'
      elif command -v pacman >/dev/null 2>&1; then
        printf '%s\n' 'pacman'
      elif command -v apt-get >/dev/null 2>&1; then
        printf '%s\n' 'apt-get'
      elif command -v apt >/dev/null 2>&1; then
        printf '%s\n' 'apt'
      else
        fail "unsupported Linux distribution: ID='${id:-unknown}', ID_LIKE='${like:-unknown}'"
      fi
      ;;
  esac
}

install_prerequisites() {
  local manager="$1"
  local -a sudo_prefix=()

  if [[ ${EUID} -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || fail 'sudo is required to install missing prerequisites'
    sudo_prefix=(sudo)
  fi

  case "$manager" in
    dnf)
      log 'Installing Fedora-family prerequisites: python3 python3-pip'
      "${sudo_prefix[@]}" dnf install -y python3 python3-pip
      ;;
    pacman)
      log 'Installing Arch-family prerequisites: python python-pip'
      "${sudo_prefix[@]}" pacman -Sy --needed --noconfirm python python-pip
      ;;
    apt-get)
      log 'Installing Debian-family prerequisites: python3 python3-pip python3-venv'
      "${sudo_prefix[@]}" apt-get update
      "${sudo_prefix[@]}" apt-get install -y python3 python3-pip python3-venv
      ;;
    apt)
      log 'Installing Debian-family prerequisites: python3 python3-pip python3-venv'
      "${sudo_prefix[@]}" apt update
      "${sudo_prefix[@]}" apt install -y python3 python3-pip python3-venv
      ;;
    *)
      fail "unsupported package manager: $manager"
      ;;
  esac
}

main() {
  local install_dev='false'
  local arg

  for arg in "$@"; do
    case "$arg" in
      --dev)
        install_dev='true'
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        usage >&2
        fail "unknown option: $arg"
        ;;
    esac
  done

  [[ "$(uname -s)" == 'Linux' ]] || fail 'Kinatio is Linux-only; this bootstrap script intentionally refuses other platforms'

  local repo_root
  repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  cd "$repo_root"

  [[ -f pyproject.toml ]] || fail 'install.sh must live in the Kinatio repository root next to pyproject.toml'

  local python_cmd=''
  if python_cmd="$(pick_python 2>/dev/null)"; then
    if python_supports_pip "$python_cmd" && python_supports_venv "$python_cmd"; then
      log "Using existing Python interpreter: $python_cmd ($(python_version "$python_cmd"))"
    else
      log "Python interpreter $python_cmd is present but missing pip or venv support; installing prerequisites"
      python_cmd=''
    fi
  fi

  if [[ -z "$python_cmd" ]]; then
    local manager
    manager="$(detect_family)"
    install_prerequisites "$manager"
    python_cmd="$(pick_python 2>/dev/null || true)"

    [[ -n "$python_cmd" ]] || fail 'no Python 3.12+ interpreter was found after installing prerequisites'
    python_supports_pip "$python_cmd" || fail "Python interpreter $python_cmd is missing pip support after prerequisite installation"
    python_supports_venv "$python_cmd" || fail "Python interpreter $python_cmd is missing venv support after prerequisite installation"

    log "Using installed Python interpreter: $python_cmd ($(python_version "$python_cmd"))"
  fi

  local venv_dir="$repo_root/.venv"
  log "Creating or refreshing local virtual environment at $venv_dir"
  "$python_cmd" -m venv "$venv_dir"

  # shellcheck disable=SC1091
  source "$venv_dir/bin/activate"

  local install_target='.'
  if [[ "$install_dev" == 'true' ]]; then
    install_target='.[dev]'
    log 'Installing Kinatio in editable mode with development extras'
  else
    log 'Installing Kinatio in editable mode'
  fi

  python -m pip install -e "$install_target"

  cat <<'EOF'

Kinatio bootstrap complete.

Recommended next steps:
  source .venv/bin/activate
  kinatio sections
  kinatio status --json
  kinatio scan system --json

Direct invocation without activating the shell session also works:
  ./.venv/bin/python -m kinatio sections
  ./.venv/bin/python -m kinatio status --json
  ./.venv/bin/python -m kinatio scan system --json
EOF
}

main "$@"
