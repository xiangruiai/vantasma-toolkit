/*
 * vchat_native/find_image_key_macos.c
 *
 * 扫 WeChat 进程内存，找解密 V2 图片 .dat 文件用的 16 字节 AES-128-ECB key。
 *
 * 算法：
 *   - 取一个本地真实 .dat 文件的 CT block 0（前 16 个加密字节）作 oracle
 *   - 扫内存所有 16 字节对齐位置，每个候选当 AES-128 key
 *   - AES-ECB 解密 CT block 0，看明文是不是图片 magic（JPEG/PNG/GIF/WebP）
 *   - 命中的就是真 key，输出 hex
 *
 * 参考算法依据：
 *   · WCDB / SQLCipher 公开技术博客（密钥存在 heap 的常驻方式）
 *   · 公开图片格式 magic：RFC 2045 / W3C PNG spec / RIFF WebP spec
 *   不抄任何第三方源码实现。
 *
 * 编译：cc -O2 -o find_image_key_macos find_image_key_macos.c -framework CommonCrypto
 *
 * 用法：sudo ./find_image_key_macos --pid <wechat-pid> --sample <dat-file>
 *       sudo ./find_image_key_macos --sample <dat-file>  (自动找 WeChat pid)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <CommonCrypto/CommonCryptor.h>

#define AES_KEY_LEN 16
#define SCAN_ALIGN  8                                    /* malloc 通常 8-16 字节对齐 */
#define MAX_REGION  (128L * 1024 * 1024)
#define V2_MAGIC_LEN 6
#define V2_HEADER   15   /* magic(6) + aes_size(4) + xor_size(4) + pad(1) */
/* 用 byte array 避免 \x 转义歧义 */
static const unsigned char V2_MAGIC[V2_MAGIC_LEN] = {0x07, 0x08, 'V', '2', 0x08, 0x07};


/* 图片 magic 验证：JPEG/PNG/GIF/WebP，前 8-16 字节 */
static int is_image_magic(const unsigned char *p) {
    if (p[0] == 0xFF && p[1] == 0xD8 && p[2] == 0xFF) {  /* JPEG */
        if (p[3] >= 0xC0 && p[3] != 0xFF) return 1;
    }
    if (p[0] == 0x89 && p[1] == 0x50 && p[2] == 0x4E && p[3] == 0x47)
        return 1;  /* PNG */
    if (p[0] == 'G' && p[1] == 'I' && p[2] == 'F' && p[3] == '8' &&
        (p[4] == '9' || p[4] == '7') && p[5] == 'a')
        return 1;  /* GIF */
    if (p[0] == 'R' && p[1] == 'I' && p[2] == 'F' && p[3] == 'F' &&
        p[8] == 'W' && p[9] == 'E' && p[10] == 'B' && p[11] == 'P')
        return 1;  /* WebP */
    if (p[0] == 'w' && p[1] == 'x' && p[2] == 'g' && p[3] == 'f')
        return 1;  /* 微信视频号短视频（HEVC 裸流） */
    return 0;
}


/* 取 .dat 文件偏移 15 后的 16 字节作为 CT block 0 */
static int read_ct_block(const char *path, unsigned char *ct_out) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    unsigned char hdr[V2_HEADER];
    if (fread(hdr, 1, V2_HEADER, f) != V2_HEADER) { fclose(f); return -1; }
    if (memcmp(hdr, V2_MAGIC, V2_MAGIC_LEN) != 0) {
        fclose(f); return -1;  /* 不是 V2 格式 */
    }
    if (fread(ct_out, 1, 16, f) != 16) { fclose(f); return -1; }
    fclose(f);
    return 0;
}


/* 尝试用 candidate key 解 CT，看明文是否图片 magic */
static int try_key(const unsigned char *key, const unsigned char *ct) {
    unsigned char pt[16];
    size_t out_len = 0;
    CCCryptorStatus s = CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionECBMode,
                                key, kCCKeySizeAES128, NULL,
                                ct, 16, pt, sizeof(pt), &out_len);
    if (s != kCCSuccess || out_len < 12) return 0;
    return is_image_magic(pt);
}


static pid_t find_wechat_pid(void) {
    FILE *fp = popen("pgrep -x WeChat", "r");
    if (!fp) return -1;
    char buf[64]; pid_t pid = -1;
    if (fgets(buf, sizeof(buf), fp)) pid = atoi(buf);
    pclose(fp);
    return pid;
}


static int scan_task(task_t task, const unsigned char *ct,
                     unsigned char *out_key) {
    mach_vm_address_t addr = 0;
    int regions = 0;
    uint64_t scanned = 0;

    while (1) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t cnt = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj;
        kern_return_t kr = mach_vm_region(task, &addr, &size,
                                           VM_REGION_BASIC_INFO_64,
                                           (vm_region_info_t)&info, &cnt, &obj);
        if (kr != KERN_SUCCESS) break;
        if (size == 0) { addr++; continue; }
        if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) !=
            (VM_PROT_READ | VM_PROT_WRITE)) {
            addr += size; continue;
        }
        if (size > MAX_REGION) {
            addr += size; continue;
        }

        regions++;
        vm_offset_t data;
        mach_msg_type_number_t dc;
        kr = mach_vm_read(task, addr, size, &data, &dc);
        if (kr == KERN_SUCCESS) {
            scanned += dc;
            const unsigned char *buf = (const unsigned char *)data;
            for (size_t off = 0; off + AES_KEY_LEN <= dc; off += SCAN_ALIGN) {
                if (try_key(buf + off, ct)) {
                    memcpy(out_key, buf + off, AES_KEY_LEN);
                    fprintf(stderr, "✓ 命中：region %d, offset %zu\n", regions, off);
                    fprintf(stderr, "  扫了 %.1f MB / %d regions\n",
                            scanned / (1024.0 * 1024.0), regions);
                    mach_vm_deallocate(mach_task_self(), data, dc);
                    return 1;
                }
            }
            mach_vm_deallocate(mach_task_self(), data, dc);
        }

        if (regions % 30 == 0) {
            fprintf(stderr, "  [%d regions, %.1f MB scanned]\n",
                    regions, scanned / (1024.0 * 1024.0));
            fflush(stderr);
        }

        addr += size;
    }

    fprintf(stderr, "完成: %d regions, %.1f MB, 未找到\n",
            regions, scanned / (1024.0 * 1024.0));
    return 0;
}


int main(int argc, char **argv) {
    pid_t pid = -1;
    const char *sample = NULL;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc)
            pid = atoi(argv[++i]);
        else if (strcmp(argv[i], "--sample") == 0 && i + 1 < argc)
            sample = argv[++i];
    }

    if (!sample) {
        fprintf(stderr, "❌ 必须 --sample <V2-format-.dat-file>\n");
        fprintf(stderr, "   找一个微信图片缓存里的 V2 .dat 文件，路径如：\n");
        fprintf(stderr, "   ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/msg/attach/<hash>/<YYYY-MM>/Img/<md5>.dat\n");
        return 2;
    }

    unsigned char ct[16];
    if (read_ct_block(sample, ct) != 0) {
        fprintf(stderr, "❌ %s 不是 V2 格式 .dat 文件\n", sample);
        return 3;
    }
    fprintf(stderr, "▶ sample: %s\n", sample);
    fprintf(stderr, "▶ CT block 0: ");
    for (int i = 0; i < 16; i++) fprintf(stderr, "%02x", ct[i]);
    fprintf(stderr, "\n");

    if (pid <= 0) {
        pid = find_wechat_pid();
        if (pid <= 0) {
            fprintf(stderr, "❌ WeChat 未运行\n");
            return 4;
        }
    }
    fprintf(stderr, "▶ WeChat pid=%d\n", pid);

    task_t task;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "❌ task_for_pid 失败: %d (需 sudo + codesign)\n", kr);
        return 5;
    }

    fprintf(stderr, "▶ 扫内存找 16 字节 AES key…\n");
    unsigned char key[AES_KEY_LEN];
    int ok = scan_task(task, ct, key);
    if (!ok) {
        fprintf(stderr, "❌ 没找到 image_aes_key（可能 WeChat 还没加载图片解密 key 到内存，先在微信里翻几张近期图片再试）\n");
        return 6;
    }

    /* 输出 JSON 到 stdout */
    printf("{\n  \"image_aes_key\": \"");
    for (int i = 0; i < AES_KEY_LEN; i++) printf("%02x", key[i]);
    printf("\",\n  \"image_xor_key\": 136\n}\n");
    return 0;
}
