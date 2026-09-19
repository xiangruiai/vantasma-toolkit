/*
 * vchat_native/find_keys_macos.c
 *
 * 从微信 macOS 主进程内存中扫 SQLCipher key（含 salt fingerprint）。
 *
 * 核心算法：WeChat 4.x 在内存中以 ASCII 模式 `x'<64hex_key><32hex_salt>'`
 * 存储每个 db 的 raw key + salt（共 99 字节字符串）。我们直接 grep 这个固定
 * 模式 —— O(N) 一次扫过整个进程内存即可，无需 AES/HMAC 校验。
 *
 * 跟传统 binary-key 扫描比的优势：
 *   · 命中率 ~ 100%（精准模式 vs 高熵启发式）
 *   · 候选数：~ 几十（一个账号最多 100 个 db）vs 数百万
 *   · 速度：CPU 内存吞吐量受限（一两秒），不需要 verify
 *
 * 输出：JSON to stdout
 *   { "<db_rel_path>": "<key_hex>", ... }
 *
 * 运行：sudo ./find_keys_macos [--pid N] [--storage-root /path]
 *
 * 编译：cc -O2 -o find_keys_macos find_keys_macos.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <dirent.h>
#include <ftw.h>
#include <pwd.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>


#define KEY_HEX_LEN   64    /* 32 字节 raw key → 64 hex */
#define SALT_HEX_LEN  32    /* 16 字节 salt → 32 hex */
#define PATTERN_LEN   (2 + KEY_HEX_LEN + SALT_HEX_LEN + 1)  /* x' + 96 hex + ' = 99 */
#define MAX_KEYS      512
#define MAX_DBS       512
#define CHUNK_SIZE    (8L * 1024 * 1024)  /* 8 MB chunks */


typedef struct {
    char key_hex[KEY_HEX_LEN + 1];
    char salt_hex[SALT_HEX_LEN + 1];
} key_entry_t;


static char g_db_rel[MAX_DBS][512];
static char g_db_salt[MAX_DBS][SALT_HEX_LEN + 1];
static int g_db_count = 0;

static key_entry_t g_keys[MAX_KEYS];
static int g_key_count = 0;

static const char *g_storage_root_for_rel = NULL;  /* nftw 回调里用 */


static int is_hex(unsigned char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}


/* 把 buf 里 96 个 hex 字符转成小写 */
static void normalize_hex(char *buf, int n) {
    for (int i = 0; i < n; i++) {
        if (buf[i] >= 'A' && buf[i] <= 'F') buf[i] += 32;
    }
}


/* 读 db 第一页前 16 字节作为 salt（hex）；明文 db 跳过返回 -1 */
static int read_db_salt(const char *path, char *salt_hex_out) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    unsigned char hdr[16];
    if (fread(hdr, 1, 16, f) != 16) { fclose(f); return -1; }
    fclose(f);
    if (memcmp(hdr, "SQLite format 3", 15) == 0) return -1;
    for (int i = 0; i < 16; i++) sprintf(salt_hex_out + i * 2, "%02x", hdr[i]);
    salt_hex_out[SALT_HEX_LEN] = 0;
    return 0;
}


static int nftw_collect_db(const char *fpath, const struct stat *sb,
                           int typeflag, struct FTW *ftw) {
    (void)sb; (void)ftw;
    if (typeflag != FTW_F) return 0;
    size_t len = strlen(fpath);
    if (len < 3 || strcmp(fpath + len - 3, ".db") != 0) return 0;
    if (g_db_count >= MAX_DBS) return 0;

    char salt[SALT_HEX_LEN + 1];
    if (read_db_salt(fpath, salt) != 0) return 0;

    strcpy(g_db_salt[g_db_count], salt);

    /* 取相对路径：从 storage_root 之后 */
    const char *rel = fpath;
    if (g_storage_root_for_rel) {
        size_t rl = strlen(g_storage_root_for_rel);
        if (strncmp(fpath, g_storage_root_for_rel, rl) == 0 &&
            fpath[rl] == '/') rel = fpath + rl + 1;
    }
    strncpy(g_db_rel[g_db_count], rel, 511);
    g_db_rel[g_db_count][511] = 0;

    g_db_count++;
    return 0;
}


/* 自动定位最新活跃的 db_storage 目录 */
static int locate_db_storages(const char *home) {
    char base[768];
    snprintf(base, sizeof(base),
        "%s/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files", home);

    DIR *d = opendir(base);
    if (!d) {
        fprintf(stderr, "❌ 找不到微信数据根 %s\n", base);
        return -1;
    }
    struct dirent *ent;
    int storages = 0;
    while ((ent = readdir(d)) != NULL) {
        if (ent->d_name[0] == '.') continue;
        if (strcmp(ent->d_name, "all_users") == 0) continue;
        char sp[1024];
        snprintf(sp, sizeof(sp), "%s/%s/db_storage", base, ent->d_name);
        struct stat st;
        if (stat(sp, &st) == 0 && S_ISDIR(st.st_mode)) {
            g_storage_root_for_rel = sp;
            int before = g_db_count;
            nftw(sp, nftw_collect_db, 20, FTW_PHYS);
            int got = g_db_count - before;
            fprintf(stderr, "  扫到 %s: +%d 个 db\n", ent->d_name, got);
            storages++;
        }
    }
    closedir(d);
    g_storage_root_for_rel = NULL;
    return storages;
}


/* 内存模式扫描：找 x'<96hex>' */
static void scan_region(const unsigned char *buf, size_t n) {
    if (n < PATTERN_LEN) return;
    for (size_t i = 0; i + PATTERN_LEN <= n; i++) {
        if (buf[i] != 'x' || buf[i + 1] != '\'') continue;
        if (buf[i + 2 + KEY_HEX_LEN + SALT_HEX_LEN] != '\'') continue;

        /* 验证 96 个 hex 字符 */
        int ok = 1;
        for (int j = 0; j < KEY_HEX_LEN + SALT_HEX_LEN; j++) {
            if (!is_hex(buf[i + 2 + j])) { ok = 0; break; }
        }
        if (!ok) continue;

        char key_hex[KEY_HEX_LEN + 1];
        char salt_hex[SALT_HEX_LEN + 1];
        memcpy(key_hex, buf + i + 2, KEY_HEX_LEN);
        memcpy(salt_hex, buf + i + 2 + KEY_HEX_LEN, SALT_HEX_LEN);
        key_hex[KEY_HEX_LEN] = 0;
        salt_hex[SALT_HEX_LEN] = 0;
        normalize_hex(key_hex, KEY_HEX_LEN);
        normalize_hex(salt_hex, SALT_HEX_LEN);

        /* 去重 */
        int dup = 0;
        for (int k = 0; k < g_key_count; k++) {
            if (strcmp(g_keys[k].key_hex, key_hex) == 0 &&
                strcmp(g_keys[k].salt_hex, salt_hex) == 0) {
                dup = 1; break;
            }
        }
        if (dup) continue;

        if (g_key_count >= MAX_KEYS) {
            fprintf(stderr, "⚠ key buffer 满\n");
            return;
        }
        strcpy(g_keys[g_key_count].key_hex, key_hex);
        strcpy(g_keys[g_key_count].salt_hex, salt_hex);
        g_key_count++;
    }
}


static int scan_task(task_t task) {
    mach_vm_address_t addr = 0;
    int regions = 0;
    uint64_t scanned = 0;

    while (1) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t info_cnt = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj;
        kern_return_t kr = mach_vm_region(task, &addr, &size,
                                           VM_REGION_BASIC_INFO_64,
                                           (vm_region_info_t)&info, &info_cnt, &obj);
        if (kr != KERN_SUCCESS) break;
        if (size == 0) { addr++; continue; }

        if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) !=
            (VM_PROT_READ | VM_PROT_WRITE)) {
            addr += size;
            continue;
        }

        regions++;
        mach_vm_address_t cur = addr;
        mach_vm_address_t end = addr + size;
        while (cur < end) {
            mach_vm_size_t cs = end - cur;
            if (cs > CHUNK_SIZE) cs = CHUNK_SIZE;

            vm_offset_t data;
            mach_msg_type_number_t dc;
            kr = mach_vm_read(task, cur, cs, &data, &dc);
            if (kr == KERN_SUCCESS) {
                scanned += dc;
                scan_region((const unsigned char *)data, dc);
                mach_vm_deallocate(mach_task_self(), data, dc);
            }
            /* 重叠 PATTERN_LEN-1 避免漏跨 chunk 边界的模式 */
            if (cs > PATTERN_LEN)
                cur += cs - (PATTERN_LEN - 1);
            else
                cur += cs;
        }

        if (regions % 20 == 0) {
            fprintf(stderr, "  [%d regions, %.1f MB, %d keys]\n",
                    regions, scanned / (1024.0 * 1024.0), g_key_count);
            fflush(stderr);
        }

        addr += size;
    }

    fprintf(stderr, "完成: %d regions, %.1f MB scanned, %d unique keys\n",
            regions, scanned / (1024.0 * 1024.0), g_key_count);
    return g_key_count;
}


static pid_t find_wechat_pid(void) {
    FILE *fp = popen("pgrep -x WeChat", "r");
    if (!fp) return -1;
    char buf[64];
    pid_t pid = -1;
    if (fgets(buf, sizeof(buf), fp)) pid = atoi(buf);
    pclose(fp);
    return pid;
}


int main(int argc, char **argv) {
    pid_t pid = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) {
            pid = atoi(argv[++i]);
        } else if (argv[i][0] >= '0' && argv[i][0] <= '9') {
            pid = atoi(argv[i]);
        }
    }
    if (pid <= 0) {
        pid = find_wechat_pid();
        if (pid <= 0) {
            fprintf(stderr, "❌ WeChat 未运行\n");
            return 2;
        }
    }
    fprintf(stderr, "▶ WeChat pid=%d\n", pid);

    /* 找真实 HOME（sudo 下 HOME 会变 /var/root） */
    const char *home = getenv("HOME");
    const char *sudo_user = getenv("SUDO_USER");
    if (sudo_user) {
        struct passwd *pw = getpwnam(sudo_user);
        if (pw && pw->pw_dir) home = pw->pw_dir;
    }
    if (!home) home = "/root";
    fprintf(stderr, "▶ HOME=%s\n", home);

    /* 收集 db salts */
    fprintf(stderr, "▶ 扫描数据目录所有加密 db …\n");
    if (locate_db_storages(home) <= 0) {
        fprintf(stderr, "❌ 没找到任何 db_storage\n");
        return 3;
    }
    fprintf(stderr, "▶ 共 %d 个加密 db\n", g_db_count);

    /* task_for_pid */
    task_t task;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "❌ task_for_pid 失败: %d\n", kr);
        fprintf(stderr, "   需要 sudo + WeChat.app ad-hoc codesigned\n");
        return 4;
    }

    fprintf(stderr, "▶ 扫描进程内存中的 key 模式 x'<96hex>' …\n");
    scan_task(task);

    /* 按 salt 匹配 key → db */
    fprintf(stderr, "▶ 匹配 key → db (按 salt fingerprint) …\n");
    int matched = 0;
    /* stdout 输出 JSON {db_rel: key_hex, ...} */
    printf("{\n");
    int first = 1;
    for (int i = 0; i < g_key_count; i++) {
        for (int j = 0; j < g_db_count; j++) {
            if (strcmp(g_keys[i].salt_hex, g_db_salt[j]) == 0) {
                printf("%s  \"%s\": \"%s\"",
                    first ? "" : ",\n",
                    g_db_rel[j], g_keys[i].key_hex);
                first = 0;
                matched++;
                break;
            }
        }
    }
    printf("\n}\n");
    fflush(stdout);

    fprintf(stderr, "✓ 匹配 %d / %d 个 db\n", matched, g_db_count);
    return (matched == g_db_count) ? 0 : (matched > 0 ? 1 : 5);
}
