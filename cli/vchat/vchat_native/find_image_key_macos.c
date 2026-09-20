/*
 * vchat_native/find_image_key_macos.c
 *
 * 扫 WeChat 进程内存，找解密 V2 图片 .dat 文件用的 16 字节 AES-128-ECB key。
 *
 * 算法：
 *   - 校验 V2 分段长度，保存最多 64 KiB 图片头以及 AES 尾块
 *   - 扫内存所有 16 字节对齐位置，每个候选当 AES-128 key
 *   - magic 只作预筛；随后校验 PKCS#7、文件尺寸及图片结构
 *   - 仅返回通过结构检查的候选；调用方仍须验证完整图像
 *
 * 参考算法依据：
 *   · WCDB / SQLCipher 公开技术博客（密钥存在 heap 的常驻方式）
 *   · 公开图片格式 magic：RFC 2045 / W3C PNG spec / RIFF WebP spec
 *   不抄任何第三方源码实现。
 *
 * 编译：make find_image_key_macos
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
#define IMAGE_PREFIX_LIMIT (64 * 1024)
#define VCHAT_IMAGE_STRUCTURE_VALIDATION 1
/* 用 byte array 避免 \x 转义歧义 */
static const unsigned char V2_MAGIC[V2_MAGIC_LEN] = {0x07, 0x08, 'V', '2', 0x08, 0x07};


typedef struct {
    unsigned char encoded[IMAGE_PREFIX_LIMIT + 16];
    unsigned char aes_tail[16], file_tail[16];
    size_t encoded_len, aes_size, aes_aligned, xor_size, plain_size, tail_len;
} image_sample;

static uint16_t be16(const unsigned char *p) { return ((uint16_t)p[0] << 8) | p[1]; }
static uint16_t le16(const unsigned char *p) { return ((uint16_t)p[1] << 8) | p[0]; }
static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static uint32_t le32(const unsigned char *p) {
    return ((uint32_t)p[3] << 24) | ((uint32_t)p[2] << 16) | ((uint32_t)p[1] << 8) | p[0];
}
static uint32_t le24(const unsigned char *p) { return ((uint32_t)p[2] << 16) | ((uint32_t)p[1] << 8) | p[0]; }

/* Cheap rejection only. A magic match is never sufficient for success. */
static int is_image_magic(const unsigned char *p) {
    if (p[0] == 0xFF && p[1] == 0xD8 && p[2] == 0xFF) {  /* JPEG */
        if (p[3] >= 0xC0 && p[3] != 0xFF) return 1;
    }
    if (memcmp(p, "\x89PNG\r\n\x1a\n", 8) == 0)
        return 1;  /* PNG */
    if (p[0] == 'G' && p[1] == 'I' && p[2] == 'F' && p[3] == '8' &&
        (p[4] == '9' || p[4] == '7') && p[5] == 'a')
        return 1;  /* GIF */
    if (p[0] == 'R' && p[1] == 'I' && p[2] == 'F' && p[3] == 'F' &&
        p[8] == 'W' && p[9] == 'E' && p[10] == 'B' && p[11] == 'P')
        return 1;  /* WebP */
    return 0;
}

static int read_image_sample(const char *path, image_sample *sample) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    memset(sample, 0, sizeof(*sample));
    unsigned char hdr[V2_HEADER];
    if (fseek(f, 0, SEEK_END) != 0) goto invalid;
    long file_len = ftell(f);
    if (file_len < V2_HEADER + 16 || fseek(f, 0, SEEK_SET) != 0) goto invalid;
    if (fread(hdr, 1, V2_HEADER, f) != V2_HEADER ||
        memcmp(hdr, V2_MAGIC, V2_MAGIC_LEN) != 0) goto invalid;
    sample->aes_size = le32(hdr + 6);
    sample->xor_size = le32(hdr + 10);
    sample->aes_aligned = sample->aes_size + (16 - sample->aes_size % 16);
    size_t payload_size = (size_t)file_len - V2_HEADER;
    if (sample->aes_size < 16 || sample->aes_aligned > payload_size ||
        sample->xor_size > payload_size - sample->aes_aligned) goto invalid;
    sample->plain_size = payload_size - (sample->aes_aligned - sample->aes_size);
    sample->encoded_len = payload_size < sizeof(sample->encoded) ? payload_size : sizeof(sample->encoded);
    if (fread(sample->encoded, 1, sample->encoded_len, f) != sample->encoded_len) goto invalid;
    if (fseek(f, (long)(V2_HEADER + sample->aes_aligned - 16), SEEK_SET) != 0 ||
        fread(sample->aes_tail, 1, 16, f) != 16) goto invalid;
    sample->tail_len = payload_size < 16 ? payload_size : 16;
    if (fseek(f, file_len - (long)sample->tail_len, SEEK_SET) != 0 ||
        fread(sample->file_tail, 1, sample->tail_len, f) != sample->tail_len) goto invalid;
    fclose(f);
    return 0;
invalid:
    fclose(f);
    return -1;
}

static int valid_dimensions(uint32_t w, uint32_t h) {
    return w > 0 && h > 0 && w <= 1000000 && h <= 1000000 && (uint64_t)w * h <= 10000000000ULL;
}

/* Walk marker segments; accept JFIF, Exif, DQT-first and progressive headers. */
static int valid_jpeg(const unsigned char *p, size_t n, size_t total) {
    if (n < 4 || p[0] != 0xff || p[1] != 0xd8) return 0;
    size_t pos = 2;
    int frame = 0, components = 0;
    unsigned char ids[4] = {0};
    while (pos < n) {
        if (p[pos++] != 0xff) return 0;
        while (pos < n && p[pos] == 0xff) pos++;
        if (pos >= n) return 0;
        unsigned char marker = p[pos++];
        if (marker == 0 || marker == 0xd8 || marker == 0xd9 ||
            marker == 1 || (marker >= 0xd0 && marker <= 0xd7)) return 0;
        if (pos + 2 > n) return 0;
        size_t length = be16(p + pos);
        if (length < 2 || length > total - pos || length > n - pos) return 0;
        const unsigned char *body = p + pos + 2;
        int sof = (marker >= 0xc0 && marker <= 0xcf &&
                   marker != 0xc4 && marker != 0xc8 && marker != 0xcc);
        if (sof) {
            if (length < 11 || (body[0] != 8 && body[0] != 12 && body[0] != 16) ||
                !valid_dimensions(be16(body + 3), be16(body + 1))) return 0;
            components = body[5];
            if (components < 1 || components > 4 || length != (size_t)(8 + 3 * components)) return 0;
            for (int i = 0; i < components; i++) {
                const unsigned char *c = body + 6 + 3 * i;
                if (!(c[1] >> 4) || (c[1] >> 4) > 4 || !(c[1] & 15) || (c[1] & 15) > 4 || c[2] > 3) return 0;
                ids[i] = c[0];
                for (int j = 0; j < i; j++) if (ids[j] == ids[i]) return 0;
            }
            frame = 1;
        } else if (marker == 0xda) {
            if (!frame || length < 8) return 0;
            int count = body[0];
            if (count < 1 || count > components || length != (size_t)(6 + 2 * count)) return 0;
            for (int i = 0; i < count; i++) {
                int known = 0;
                for (int j = 0; j < components; j++) known |= body[1 + 2*i] == ids[j];
                if (!known || (body[2 + 2*i] >> 4) > 3 || (body[2 + 2*i] & 15) > 3) return 0;
            }
            const unsigned char *params = body + 1 + 2 * count;
            if (params[0] > 63 || params[1] > 63 || (params[2] >> 4) > 13 || (params[2] & 15) > 13) return 0;
            return pos + length + 2 <= total;
        }
        pos += length;
    }
    return 0;
}

static uint32_t png_crc(const unsigned char *p, size_t n) {
    uint32_t crc = 0xffffffffU;
    for (size_t i = 0; i < n; i++) {
        crc ^= p[i];
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}

static int valid_png(const unsigned char *p, size_t n, size_t total) {
    if (n < 33 || total < 45 || memcmp(p, "\x89PNG\r\n\x1a\n", 8) ||
        be32(p + 8) != 13 || memcmp(p + 12, "IHDR", 4) ||
        !valid_dimensions(be32(p + 16), be32(p + 20)) || p[26] || p[27] || p[28] > 1 ||
        png_crc(p + 12, 17) != be32(p + 29)) return 0;
    unsigned char depth = p[24], color = p[25];
    if (color == 0) return depth == 1 || depth == 2 || depth == 4 || depth == 8 || depth == 16;
    if (color == 3) return depth == 1 || depth == 2 || depth == 4 || depth == 8;
    if (color == 2 || color == 4 || color == 6) return depth == 8 || depth == 16;
    return 0;
}

static int valid_gif(const unsigned char *p, size_t n, size_t total) {
    if (n < 13 || (memcmp(p, "GIF87a", 6) && memcmp(p, "GIF89a", 6)) ||
        !valid_dimensions(le16(p + 6), le16(p + 8))) return 0;
    size_t pos = 13;
    if (p[10] & 0x80) {
        size_t colors = (size_t)1 << ((p[10] & 7) + 1);
        if (p[11] >= colors) return 0;
        pos += 3 * colors;
    }
    while (pos < n && pos < total) {
        unsigned char marker = p[pos++];
        if (marker == 0x21) {
            if (pos >= n) return 0;
            pos++; /* extension label, followed by length-prefixed subblocks */
            for (;;) {
                if (pos >= n) return 0;
                size_t count = p[pos++];
                if (!count) break;
                if (count > n - pos || count > total - pos) return 0;
                pos += count;
            }
        } else if (marker == 0x2c) {
            if (pos + 9 > n) return 0;
            uint32_t x = le16(p + pos), y = le16(p + pos + 2);
            uint32_t w = le16(p + pos + 4), h = le16(p + pos + 6);
            if (!valid_dimensions(w, h) || x + w > le16(p + 6) || y + h > le16(p + 8) || (p[pos + 8] & 0x18)) return 0;
            unsigned char packed = p[pos + 8];
            pos += 9;
            if (packed & 0x80) pos += (size_t)3 << ((packed & 7) + 1);
            if (pos + 2 > n || p[pos] < 2 || p[pos] > 8 || p[pos + 1] == 0) return 0;
            return pos + 2 + p[pos + 1] <= total;
        } else return 0;
    }
    return 0;
}

static int valid_webp(const unsigned char *p, size_t n, size_t total) {
    if (n < 25 || memcmp(p, "RIFF", 4) || memcmp(p + 8, "WEBP", 4) ||
        (uint64_t)le32(p + 4) + 8 != total) return 0;
    uint32_t length = le32(p + 16);
    if ((uint64_t)20 + length + (length & 1) > total) return 0;
    if (!memcmp(p + 12, "VP8 ", 4)) {
        return n >= 30 && length >= 10 && !(p[20] & 1) && !memcmp(p + 23, "\x9d\x01\x2a", 3) &&
               valid_dimensions(le16(p + 26) & 0x3fff, le16(p + 28) & 0x3fff);
    }
    if (!memcmp(p + 12, "VP8L", 4)) {
        uint32_t bits = le32(p + 21);
        return length >= 5 && p[20] == 0x2f && !(bits >> 29) &&
               valid_dimensions((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1);
    }
    if (!memcmp(p + 12, "VP8X", 4)) {
        return n >= 30 && length == 10 && !(p[20] & ~0x3e) && !p[21] && !p[22] && !p[23] &&
               valid_dimensions(le24(p + 24) + 1, le24(p + 27) + 1);
    }
    return 0;
}

static int valid_image_structure(const unsigned char *p, size_t n, size_t total) {
    return valid_jpeg(p, n, total) || valid_png(p, n, total) ||
           valid_gif(p, n, total) || valid_webp(p, n, total);
}

/* Candidate validation does no process access and is exercised by a C harness. */
static int try_key(const unsigned char *key, const image_sample *sample, unsigned char *xor_out) {
    unsigned char pt[16];
    size_t out_len = 0;
    CCCryptorStatus s = CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionECBMode,
                                key, kCCKeySizeAES128, NULL,
                                sample->encoded, 16, pt, sizeof(pt), &out_len);
    if (s != kCCSuccess || out_len != 16 || !is_image_magic(pt)) return 0;

    unsigned char padding[16];
    s = CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionECBMode, key, kCCKeySizeAES128, NULL,
                sample->aes_tail, 16, padding, sizeof(padding), &out_len);
    size_t pad = sample->aes_aligned - sample->aes_size;
    if (s != kCCSuccess || out_len != 16) return 0;
    for (size_t i = 16 - pad; i < 16; i++) if (padding[i] != pad) return 0;

    unsigned char xor_key = 0x88;
    static const unsigned char jpeg_end[] = {0xff, 0xd9};
    static const unsigned char png_end[] = {0,0,0,0,'I','E','N','D',0xae,0x42,0x60,0x82};
    const unsigned char *end = NULL;
    size_t end_len = 0;
    if (pt[0] == 0xff && pt[1] == 0xd8) { end = jpeg_end; end_len = sizeof(jpeg_end); }
    else if (pt[0] == 0x89) { end = png_end; end_len = sizeof(png_end); }
    if (end && sample->xor_size >= end_len && sample->tail_len >= end_len) {
        const unsigned char *tail = sample->file_tail + sample->tail_len - end_len;
        unsigned char derived = tail[0] ^ end[0];
        int consistent = 1;
        for (size_t i = 1; i < end_len; i++) consistent &= (tail[i] ^ end[i]) == derived;
        if (consistent) xor_key = derived;
    }
    size_t prefix_len = sample->plain_size < IMAGE_PREFIX_LIMIT ? sample->plain_size : IMAGE_PREFIX_LIMIT;
    size_t encrypted_len = sample->aes_aligned < IMAGE_PREFIX_LIMIT ? sample->aes_aligned : IMAGE_PREFIX_LIMIT;
    unsigned char prefix[IMAGE_PREFIX_LIMIT];
    s = CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionECBMode, key, kCCKeySizeAES128, NULL,
                sample->encoded, encrypted_len, prefix, sizeof(prefix), &out_len);
    if (s != kCCSuccess || out_len != encrypted_len) return 0;
    for (size_t i = sample->aes_size; i < prefix_len; i++) {
        size_t encoded_pos = sample->aes_aligned + i - sample->aes_size;
        if (encoded_pos >= sample->encoded_len) return 0;
        prefix[i] = sample->encoded[encoded_pos];
        if (i >= sample->plain_size - sample->xor_size) prefix[i] ^= xor_key;
    }
    if (!valid_image_structure(prefix, prefix_len, sample->plain_size)) return 0;
    *xor_out = xor_key;
    return 1;
}


static pid_t find_wechat_pid(void) {
    FILE *fp = popen("pgrep -x WeChat", "r");
    if (!fp) return -1;
    char buf[64]; pid_t pid = -1;
    if (fgets(buf, sizeof(buf), fp)) pid = atoi(buf);
    pclose(fp);
    return pid;
}


static int scan_task(task_t task, const image_sample *sample,
                     unsigned char *out_key, unsigned char *xor_out) {
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
                if (try_key(buf + off, sample, xor_out)) {
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

    image_sample image;
    if (read_image_sample(sample, &image) != 0) {
        fprintf(stderr, "❌ 图片样本的 V2 格式或分段长度无效\n");
        return 3;
    }
    fprintf(stderr, "▶ sample: %s\n", sample);

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
    unsigned char xor_key = 0x88;
    int ok = scan_task(task, &image, key, &xor_key);
    if (!ok) {
        fprintf(stderr, "❌ 没找到 image_aes_key（可能 WeChat 还没加载图片解密 key 到内存，先在微信里翻几张近期图片再试）\n");
        return 6;
    }

    /* 输出 JSON 到 stdout */
    printf("{\n  \"image_aes_key\": \"");
    for (int i = 0; i < AES_KEY_LEN; i++) printf("%02x", key[i]);
    printf("\",\n  \"image_xor_key\": %u\n}\n", xor_key);
    return 0;
}
