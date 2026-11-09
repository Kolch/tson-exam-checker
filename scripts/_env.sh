# shellcheck shell=bash
# Shared environment for scripts/*.sh — source it, don't run it.
# Values come from the real environment, then .env, then the defaults below.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT

_env_get() { # $1 = key -> its value from .env (last wins), empty if absent
  [ -f "$PROJECT_ROOT/.env" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$PROJECT_ROOT/.env" | tail -n 1 \
    | sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//"
}

BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"

ANDROID_HOME="${ANDROID_HOME:-$(_env_get ANDROID_HOME)}"
ANDROID_HOME="${ANDROID_HOME:-$BREW_PREFIX/share/android-commandlinetools}"
export ANDROID_HOME
export ANDROID_SDK_ROOT="$ANDROID_HOME"

TSON_AVD="${TSON_AVD:-$(_env_get TSON_AVD)}"
TSON_AVD="${TSON_AVD:-tson}"
export TSON_AVD

export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$BREW_PREFIX/bin:$PATH"

# Java 21 for Appium's uiautomator2 driver and the SDK tools: a system JDK
# if one is registered, else Homebrew's keg-only openjdk@21.
if [ -z "${JAVA_HOME:-}" ]; then
  JAVA_HOME="$(/usr/libexec/java_home -F -v 21 2>/dev/null || true)"
  if [ -z "$JAVA_HOME" ] && [ -d "$BREW_PREFIX/opt/openjdk@21" ]; then
    JAVA_HOME="$BREW_PREFIX/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
  fi
  export JAVA_HOME
fi
