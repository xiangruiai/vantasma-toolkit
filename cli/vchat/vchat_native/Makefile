# vchat_native · macOS 内存扫描工具
#
# 编译目标：
#   find_keys_macos       — SQLCipher db key 扫描
#   find_image_key_macos  — 图片 .dat 解密用的 AES key 扫描
#
# 用法（在仓库根目录）：
#   make -C vchat_native
#   sudo vchat_native/find_keys_macos
#   sudo vchat_native/find_image_key_macos --sample <.dat 文件>

CC ?= clang
CFLAGS ?= -O2 -Wall -Wno-deprecated-declarations

.PHONY: all clean

all: find_keys_macos find_image_key_macos

find_keys_macos: find_keys_macos.c
	$(CC) $(CFLAGS) -o $@ $< -framework Foundation

find_image_key_macos: find_image_key_macos.c
	$(CC) $(CFLAGS) -o $@ $< -framework CoreFoundation -framework Security

clean:
	rm -f find_keys_macos find_image_key_macos
