#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENTITLEMENTS_FILE="$SKILL_DIR/assets/runtime-entitlements.plist"

OLD_DATA_TOKEN="LarkShell"
NEW_DATA_TOKEN="${FEISHU_MULTI_DATA_TOKEN:-LarkDual2}"
OLD_BUNDLE_PREFIX="com.electron.lark"
NEW_BUNDLE_PREFIX="${FEISHU_MULTI_BUNDLE_PREFIX:-com.electron.lar2}"

SOURCE_APP="${FEISHU_MULTI_SOURCE_APP:-}"
DEST_DIR="${FEISHU_MULTI_DEST_DIR:-}"
APP_NAME="${FEISHU_MULTI_APP_NAME:-飞书双开.app}"
STABILITY_SECONDS="${FEISHU_MULTI_STABILITY_SECONDS:-40}"
COMMAND="${1:-auto}"

if [[ $# -gt 0 ]]; then
  shift
fi

log() {
  printf '[feishu-multi] %s\n' "$*"
}

warn() {
  printf '[feishu-multi] 警告: %s\n' "$*" >&2
}

die() {
  printf '[feishu-multi] 错误: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法: feishu-multi.sh [auto|setup|start|rebuild|status|stop] [选项]

命令:
  auto      副本不存在或版本过期时自动重建，然后启动两个原生飞书
  setup     创建副本，不启动；已存在健康的同版本副本时不重建
  start     启动原飞书和已有副本
  rebuild   安全归档旧副本，基于当前官方飞书重建并启动
  status    检查版本、签名、主进程和独立数据目录
  stop      仅退出副本，不退出原飞书

选项:
  --source-app PATH       官方飞书 App 路径，默认自动查找 /Applications/Lark.app
  --dest-dir PATH         副本安装目录，默认优先 /Applications
  --app-name NAME.app     副本名称，默认 飞书双开.app
  --stability-seconds N   重建后稳定性验证时长，默认 40 秒
  -h, --help              显示帮助

环境变量:
  FEISHU_MULTI_SOURCE_APP
  FEISHU_MULTI_DEST_DIR
  FEISHU_MULTI_APP_NAME
  FEISHU_MULTI_STABILITY_SECONDS
  FEISHU_MULTI_DATA_TOKEN       必须与 LarkShell 等长（9 个 ASCII 字符）
  FEISHU_MULTI_BUNDLE_PREFIX    必须与 com.electron.lark 等长
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-app)
      [[ $# -ge 2 ]] || die '--source-app 缺少路径'
      SOURCE_APP="$2"
      shift 2
      ;;
    --dest-dir)
      [[ $# -ge 2 ]] || die '--dest-dir 缺少路径'
      DEST_DIR="$2"
      shift 2
      ;;
    --app-name)
      [[ $# -ge 2 ]] || die '--app-name 缺少名称'
      APP_NAME="$2"
      shift 2
      ;;
    --stability-seconds)
      [[ $# -ge 2 ]] || die '--stability-seconds 缺少秒数'
      STABILITY_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知选项: $1"
      ;;
  esac
done

case "$COMMAND" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

require_macos() {
  [[ "$(/usr/bin/uname -s)" == "Darwin" ]] || die '仅支持 macOS'
}

require_tools() {
  local tool
  for tool in \
    /usr/bin/codesign \
    /usr/bin/ditto \
    /usr/bin/file \
    /usr/bin/find \
    /usr/bin/grep \
    /usr/bin/open \
    /usr/bin/perl \
    /usr/bin/pgrep \
    /usr/bin/xattr \
    /usr/libexec/PlistBuddy; do
    [[ -x "$tool" ]] || die "缺少系统工具: $tool"
  done
  [[ -f "$ENTITLEMENTS_FILE" ]] || die "缺少 entitlements: $ENTITLEMENTS_FILE"
  /usr/bin/plutil -lint "$ENTITLEMENTS_FILE" >/dev/null || die 'runtime-entitlements.plist 格式错误'
}

validate_configuration() {
  [[ "$APP_NAME" == *.app ]] || die '--app-name 必须以 .app 结尾'
  [[ "$APP_NAME" != */* ]] || die '--app-name 不能包含路径分隔符'
  [[ "$STABILITY_SECONDS" =~ ^[0-9]+$ ]] || die '--stability-seconds 必须是非负整数'
  [[ ${#NEW_DATA_TOKEN} -eq ${#OLD_DATA_TOKEN} ]] || \
    die "数据目录标识必须与 $OLD_DATA_TOKEN 等长"
  [[ "$NEW_DATA_TOKEN" =~ ^[A-Za-z0-9]+$ ]] || die '数据目录标识只能使用 ASCII 字母和数字'
  [[ ${#NEW_BUNDLE_PREFIX} -eq ${#OLD_BUNDLE_PREFIX} ]] || \
    die "Bundle 前缀必须与 $OLD_BUNDLE_PREFIX 等长"
  [[ "$NEW_BUNDLE_PREFIX" =~ ^[A-Za-z0-9.]+$ ]] || die 'Bundle 前缀包含不安全字符'
}

plist_read() {
  local key="$1"
  local plist="$2"
  /usr/libexec/PlistBuddy -c "Print :$key" "$plist" 2>/dev/null
}

find_source_app() {
  local candidate
  local candidates=(
    "/Applications/Lark.app"
    "/Applications/Feishu.app"
    "/Applications/飞书.app"
    "$HOME/Applications/Lark.app"
    "$HOME/Applications/Feishu.app"
    "$HOME/Applications/飞书.app"
  )

  if [[ -n "$SOURCE_APP" ]]; then
    [[ -d "$SOURCE_APP" ]] || die "未找到源 App: $SOURCE_APP"
    return
  fi

  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" ]]; then
      SOURCE_APP="$candidate"
      return
    fi
  done
  die '未找到官方飞书客户端，请先从飞书官网安装，或使用 --source-app 指定路径'
}

validate_source_app() {
  local source_plist="$SOURCE_APP/Contents/Info.plist"
  local source_bundle
  local source_executable

  [[ -f "$source_plist" ]] || die "源 App 缺少 Info.plist: $SOURCE_APP"
  source_bundle="$(plist_read CFBundleIdentifier "$source_plist" || true)"
  source_executable="$(plist_read CFBundleExecutable "$source_plist" || true)"
  [[ "$source_bundle" == "$OLD_BUNDLE_PREFIX" ]] || \
    die "不支持的源 App Bundle ID: ${source_bundle:-<empty>}（期望 $OLD_BUNDLE_PREFIX）"
  [[ -n "$source_executable" && -x "$SOURCE_APP/Contents/MacOS/$source_executable" ]] || \
    die '源 App 主程序不可用'
}

resolve_destination() {
  local source_canonical
  local destination_canonical

  if [[ -z "$DEST_DIR" ]]; then
    if [[ -e "/Applications/$APP_NAME" || -w "/Applications" ]]; then
      DEST_DIR="/Applications"
    else
      DEST_DIR="$HOME/Applications"
      warn "/Applications 不可写，将副本安装到 $DEST_DIR"
    fi
  fi

  /bin/mkdir -p "$DEST_DIR"
  [[ -d "$DEST_DIR" && -w "$DEST_DIR" ]] || die "目标目录不可写: $DEST_DIR"
  DEST_APP="$DEST_DIR/$APP_NAME"
  source_canonical="$(cd "$(dirname "$SOURCE_APP")" && pwd -P)/$(basename "$SOURCE_APP")"
  destination_canonical="$(cd "$DEST_DIR" && pwd -P)/$APP_NAME"
  [[ "$destination_canonical" != "$source_canonical" ]] || \
    die '副本目标不能与官网版飞书是同一路径'
  BACKUP_DIR="$HOME/Applications/Feishu Multi Backups"
  /bin/mkdir -p "$BACKUP_DIR"
}

app_version() {
  local app_path="$1"
  plist_read CFBundleShortVersionString "$app_path/Contents/Info.plist" || true
}

app_executable_path() {
  local app_path="$1"
  local executable
  executable="$(plist_read CFBundleExecutable "$app_path/Contents/Info.plist" || true)"
  [[ -n "$executable" ]] || return 1
  printf '%s/Contents/MacOS/%s\n' "$app_path" "$executable"
}

pid_for_binary() {
  local binary_path="$1"
  local matches
  matches="$(/usr/bin/pgrep -f -x "$binary_path" 2>/dev/null || true)"
  printf '%s\n' "$matches" | /usr/bin/sed -n '1p'
}

pid_for_app() {
  local app_path="$1"
  local binary_path
  binary_path="$(app_executable_path "$app_path" || true)"
  [[ -n "$binary_path" ]] || return 0
  pid_for_binary "$binary_path"
}

stop_clone() {
  local clone_pid
  local attempt
  clone_pid="$(pid_for_app "$DEST_APP")"
  if [[ -z "$clone_pid" ]]; then
    log '副本未运行'
    return
  fi

  log "正在退出副本 PID $clone_pid"
  /bin/kill -TERM "$clone_pid"
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! /bin/kill -0 "$clone_pid" 2>/dev/null; then
      log '副本已退出'
      return
    fi
    /bin/sleep 1
  done
  die '副本未在 10 秒内退出，为避免破坏数据已停止重建'
}

patch_info_plists() {
  local stage_app="$1"
  local plist
  local current_id
  local new_id

  while IFS= read -r -d '' plist; do
    current_id="$(plist_read CFBundleIdentifier "$plist" || true)"
    case "$current_id" in
      "$OLD_BUNDLE_PREFIX"*)
        new_id="${current_id/$OLD_BUNDLE_PREFIX/$NEW_BUNDLE_PREFIX}"
        /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $new_id" "$plist"
        ;;
    esac
  done < <(/usr/bin/find "$stage_app/Contents" -type f -name Info.plist -print0)

  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $NEW_BUNDLE_PREFIX" \
    "$stage_app/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName ${APP_NAME%.app}" \
    "$stage_app/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :CFBundleURLTypes:0:CFBundleURLName $NEW_BUNDLE_PREFIX" \
    "$stage_app/Contents/Info.plist" 2>/dev/null || true
}

patch_macho_files() {
  local stage_app="$1"
  local candidate
  local file_type
  local patched_count=0
  local old_token_found=0
  PATCHED_MACHOS=()

  while IFS= read -r -d '' candidate; do
    file_type="$(/usr/bin/file -b "$candidate")"
    case "$file_type" in
      *Mach-O*)
        if /usr/bin/grep -aFq "$OLD_DATA_TOKEN" "$candidate" || \
           /usr/bin/grep -aFq "$OLD_BUNDLE_PREFIX" "$candidate"; then
          OLD_TOKEN="$OLD_DATA_TOKEN" NEW_TOKEN="$NEW_DATA_TOKEN" \
          OLD_PREFIX="$OLD_BUNDLE_PREFIX" NEW_PREFIX="$NEW_BUNDLE_PREFIX" \
            /usr/bin/perl -pi -e \
            's/\Q$ENV{OLD_TOKEN}\E/$ENV{NEW_TOKEN}/g; s/\Q$ENV{OLD_PREFIX}\E/$ENV{NEW_PREFIX}/g' \
            "$candidate"
          PATCHED_MACHOS[${#PATCHED_MACHOS[@]}]="$candidate"
          patched_count=$((patched_count + 1))
        fi
        ;;
    esac
  done < <(/usr/bin/find "$stage_app/Contents" -type f -print0)

  [[ $patched_count -gt 0 ]] || die '未在客户端中找到可补丁的 Mach-O 文件，当前飞书版本可能已改变内部结构'

  for candidate in "${PATCHED_MACHOS[@]}"; do
    if /usr/bin/grep -aFq "$OLD_DATA_TOKEN" "$candidate" || \
       /usr/bin/grep -aFq "$OLD_BUNDLE_PREFIX" "$candidate"; then
      warn "补丁后仍发现旧标识: $candidate"
      old_token_found=1
    fi
  done
  [[ $old_token_found -eq 0 ]] || die '二进制补丁未完整应用'
  log "已补丁 $patched_count 个 Mach-O 文件"
}

sign_clone() {
  local stage_app="$1"
  local macho_file
  local nested_app
  local framework

  /usr/bin/xattr -dr com.apple.quarantine "$stage_app" 2>/dev/null || true

  for macho_file in "${PATCHED_MACHOS[@]}"; do
    /usr/bin/codesign --force --sign - --timestamp=none --options runtime "$macho_file"
  done

  while IFS= read -r -d '' nested_app; do
    /usr/bin/codesign --force --sign - --timestamp=none --options runtime \
      --entitlements "$ENTITLEMENTS_FILE" "$nested_app"
  done < <(/usr/bin/find "$stage_app/Contents" -depth -type d -name '*.app' -print0)

  while IFS= read -r -d '' framework; do
    /usr/bin/codesign --force --sign - --timestamp=none --options runtime "$framework"
  done < <(/usr/bin/find "$stage_app/Contents" -depth -type d -name '*.framework' -print0)

  /usr/bin/codesign --force --sign - --timestamp=none --options runtime \
    --entitlements "$ENTITLEMENTS_FILE" "$stage_app"
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$stage_app"
}

archive_existing_clone() {
  local timestamp
  local backup_path
  timestamp="$(/bin/date +%Y%m%d-%H%M%S)"
  backup_path="$BACKUP_DIR/${APP_NAME%.app}-$timestamp.app"
  /bin/mv "$DEST_APP" "$backup_path"
  LAST_BACKUP_PATH="$backup_path"
  log "旧副本已归档: $backup_path"
}

build_clone() {
  local timestamp
  local stage_app
  local source_version
  local stage_version
  local stage_bundle

  if [[ -d "$DEST_APP" ]]; then
    stop_clone
  fi

  timestamp="$(/bin/date +%Y%m%d-%H%M%S)"
  stage_app="$DEST_DIR/.feishu-multi-build-$timestamp-$$.app"
  [[ ! -e "$stage_app" ]] || die "临时构建路径已存在: $stage_app"
  log "复制官方飞书到临时副本: $stage_app"
  /usr/bin/ditto "$SOURCE_APP" "$stage_app"

  patch_info_plists "$stage_app"
  patch_macho_files "$stage_app"
  sign_clone "$stage_app"

  source_version="$(app_version "$SOURCE_APP")"
  stage_version="$(app_version "$stage_app")"
  stage_bundle="$(plist_read CFBundleIdentifier "$stage_app/Contents/Info.plist" || true)"
  [[ "$stage_version" == "$source_version" ]] || die '副本与源 App 版本不一致'
  [[ "$stage_bundle" == "$NEW_BUNDLE_PREFIX" ]] || die "副本 Bundle ID 校验失败: $stage_bundle"

  LAST_BACKUP_PATH=""
  if [[ -e "$DEST_APP" ]]; then
    archive_existing_clone
  fi

  if ! /bin/mv "$stage_app" "$DEST_APP"; then
    if [[ -n "$LAST_BACKUP_PATH" && -e "$LAST_BACKUP_PATH" && ! -e "$DEST_APP" ]]; then
      /bin/mv "$LAST_BACKUP_PATH" "$DEST_APP"
      warn '新副本安装失败，已恢复旧副本'
    fi
    die '无法安装新副本'
  fi

  /usr/bin/codesign --verify --deep --strict "$DEST_APP"
  log "副本已安装: $DEST_APP"
  log "独立数据目录: $HOME/Library/Application Support/$NEW_DATA_TOKEN"
}

clone_is_current_and_valid() {
  local source_version
  local clone_version
  local clone_bundle
  [[ -d "$DEST_APP" ]] || return 1

  source_version="$(app_version "$SOURCE_APP")"
  clone_version="$(app_version "$DEST_APP")"
  clone_bundle="$(plist_read CFBundleIdentifier "$DEST_APP/Contents/Info.plist" || true)"
  [[ "$source_version" == "$clone_version" ]] || return 1
  [[ "$clone_bundle" == "$NEW_BUNDLE_PREFIX" ]] || return 1
  /usr/bin/codesign --verify --deep --strict "$DEST_APP" >/dev/null 2>&1 || return 1
  return 0
}

start_apps() {
  local verify_seconds="$1"
  local clone_binary
  local clone_pid=""
  local attempt

  [[ -d "$DEST_APP" ]] || die '副本不存在，请先运行 auto 或 setup'
  /usr/bin/open "$SOURCE_APP"
  /usr/bin/open -n "$DEST_APP"

  clone_binary="$(app_executable_path "$DEST_APP")"
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    clone_pid="$(pid_for_binary "$clone_binary")"
    [[ -n "$clone_pid" ]] && break
    /bin/sleep 1
  done
  [[ -n "$clone_pid" ]] || die '副本主进程未启动'

  if [[ "$verify_seconds" -gt 0 ]]; then
    log "正在验证副本稳定性（${verify_seconds} 秒）..."
    /bin/sleep "$verify_seconds"
    /bin/kill -0 "$clone_pid" 2>/dev/null || \
      die '副本在稳定性验证期内退出，请查看 ~/Library/Logs/DiagnosticReports 中的 Feishu/Lark Helper 报告'
  fi
  log "原生飞书双开成功，副本 PID: $clone_pid"
}

show_status() {
  local source_pid
  local clone_pid
  local source_binary
  local clone_binary=""
  local signature_status='不存在'

  source_binary="$(app_executable_path "$SOURCE_APP")"
  source_pid="$(pid_for_binary "$source_binary")"
  if [[ -d "$DEST_APP" ]]; then
    clone_binary="$(app_executable_path "$DEST_APP" || true)"
    clone_pid="$(pid_for_binary "$clone_binary")"
    if /usr/bin/codesign --verify --deep --strict "$DEST_APP" >/dev/null 2>&1; then
      signature_status='通过'
    else
      signature_status='失败'
    fi
  else
    clone_pid=""
  fi

  printf '源 App: %s\n' "$SOURCE_APP"
  printf '源版本: %s\n' "$(app_version "$SOURCE_APP")"
  printf '源进程: %s\n' "${source_pid:-未运行}"
  printf '副本: %s\n' "$DEST_APP"
  printf '副本版本: %s\n' "$([[ -d "$DEST_APP" ]] && app_version "$DEST_APP" || printf '不存在')"
  printf '副本进程: %s\n' "${clone_pid:-未运行}"
  printf '副本签名: %s\n' "$signature_status"
  printf '副本数据: %s\n' "$HOME/Library/Application Support/$NEW_DATA_TOKEN"
}

main() {
  require_macos
  require_tools
  validate_configuration
  find_source_app
  validate_source_app
  resolve_destination

  case "$COMMAND" in
    auto)
      if clone_is_current_and_valid; then
        log '副本已是当前版本且签名有效'
        start_apps 5
      else
        build_clone
        start_apps "$STABILITY_SECONDS"
      fi
      ;;
    setup)
      if clone_is_current_and_valid; then
        log "副本已就绪: $DEST_APP"
      else
        build_clone
      fi
      ;;
    start)
      start_apps 5
      ;;
    rebuild)
      build_clone
      start_apps "$STABILITY_SECONDS"
      ;;
    status)
      show_status
      ;;
    stop)
      stop_clone
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      die "未知命令: $COMMAND"
      ;;
  esac
}

main
