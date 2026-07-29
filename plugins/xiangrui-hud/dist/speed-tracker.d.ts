import type { StdinData } from './types.js';
export type SpeedTrackerDeps = {
    homeDir: () => string;
    now: () => number;
};
export declare function getOutputSpeed(stdin: StdinData, overrides?: Partial<SpeedTrackerDeps>): number | null;
//# sourceMappingURL=speed-tracker.d.ts.map