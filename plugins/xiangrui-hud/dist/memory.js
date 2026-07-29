import os from 'node:os';
import { execFileSync } from 'node:child_process';
export function parseVmStat(output) {
    const pageSizeMatch = output.match(/page size of (\d+) bytes/);
    if (!pageSizeMatch)
        return null;
    const activeMatch = output.match(/Pages active:\s+(\d+)/);
    const wiredMatch = output.match(/Pages wired down:\s+(\d+)/);
    if (!activeMatch || !wiredMatch)
        return null;
    return {
        pageSize: Number(pageSizeMatch[1]),
        active: Number(activeMatch[1]),
        wired: Number(wiredMatch[1]),
    };
}
const readDefaultMemory = () => ({
    totalBytes: os.totalmem(),
    freeBytes: os.freemem(),
});
const readMacOSMemory = () => {
    try {
        const output = execFileSync('/usr/bin/vm_stat', {
            encoding: 'utf8',
            timeout: 5000,
        });
        const parsed = parseVmStat(output);
        if (!parsed)
            return readDefaultMemory();
        const totalBytes = os.totalmem();
        const usedBytes = (parsed.active + parsed.wired) * parsed.pageSize;
        return { totalBytes, freeBytes: totalBytes - usedBytes };
    }
    catch {
        return readDefaultMemory();
    }
};
let readMemory = process.platform === 'darwin' ? readMacOSMemory : readDefaultMemory;
export async function getMemoryUsage() {
    try {
        const { totalBytes, freeBytes } = readMemory();
        if (!Number.isFinite(totalBytes) || totalBytes <= 0) {
            return null;
        }
        const safeFreeBytes = Number.isFinite(freeBytes)
            ? Math.min(Math.max(freeBytes, 0), totalBytes)
            : 0;
        const usedBytes = totalBytes - safeFreeBytes;
        const usedPercent = Math.round((usedBytes / totalBytes) * 100);
        return {
            totalBytes,
            usedBytes,
            freeBytes: safeFreeBytes,
            usedPercent: Math.min(Math.max(usedPercent, 0), 100),
        };
    }
    catch {
        return null;
    }
}
export function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) {
        return '0 B';
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    const fractionDigits = value >= 10 || unitIndex === 0 ? 0 : 1;
    return `${value.toFixed(fractionDigits)} ${units[unitIndex]}`;
}
export function _setMemoryReaderForTests(reader) {
    readMemory = reader ?? (process.platform === 'darwin' ? readMacOSMemory : readDefaultMemory);
}
//# sourceMappingURL=memory.js.map