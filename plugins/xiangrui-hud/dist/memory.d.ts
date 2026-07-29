import type { MemoryInfo } from './types.js';
type MemoryReader = () => {
    totalBytes: number;
    freeBytes: number;
};
export declare function parseVmStat(output: string): {
    pageSize: number;
    active: number;
    wired: number;
} | null;
export declare function getMemoryUsage(): Promise<MemoryInfo | null>;
export declare function formatBytes(bytes: number): string;
export declare function _setMemoryReaderForTests(reader: MemoryReader | null): void;
export {};
//# sourceMappingURL=memory.d.ts.map