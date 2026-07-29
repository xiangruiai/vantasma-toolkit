import type { SessionTokenUsage, StdinData } from './types.js';
export interface SessionCostEstimate {
    totalUsd: number;
    inputUsd: number;
    cacheCreationUsd: number;
    cacheReadUsd: number;
    outputUsd: number;
}
export interface SessionCostDisplay {
    totalUsd: number;
    source: 'native' | 'estimate';
}
export declare function estimateSessionCost(stdin: StdinData, sessionTokens: SessionTokenUsage | undefined): SessionCostEstimate | null;
export declare function resolveSessionCost(stdin: StdinData, sessionTokens: SessionTokenUsage | undefined): SessionCostDisplay | null;
export declare function formatUsd(amount: number): string;
//# sourceMappingURL=cost.d.ts.map