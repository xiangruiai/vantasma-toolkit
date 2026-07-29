import { getProviderLabel } from './stdin.js';
const TOKENS_PER_MILLION = 1_000_000;
const CACHE_WRITE_MULTIPLIER = 1.25;
const CACHE_READ_MULTIPLIER = 0.1;
const ANTHROPIC_MODEL_PRICING = [
    { pattern: /\bopus 4(?: \d+)?\b/i, pricing: { inputUsdPerMillion: 15, outputUsdPerMillion: 75 } },
    { pattern: /\bsonnet 4(?: \d+)?\b/i, pricing: { inputUsdPerMillion: 3, outputUsdPerMillion: 15 } },
    { pattern: /\bsonnet 3 7\b/i, pricing: { inputUsdPerMillion: 3, outputUsdPerMillion: 15 } },
    { pattern: /\bsonnet 3 5\b/i, pricing: { inputUsdPerMillion: 3, outputUsdPerMillion: 15 } },
    { pattern: /\bhaiku 3 5\b/i, pricing: { inputUsdPerMillion: 0.8, outputUsdPerMillion: 4 } },
];
function normalizeModelName(modelName) {
    return modelName
        .toLowerCase()
        .replace(/^claude\s+/, '')
        .replace(/\([^)]*\)/g, ' ')
        .replace(/[._-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}
function matchAnthropicPricing(modelName) {
    const normalized = normalizeModelName(modelName);
    for (const entry of ANTHROPIC_MODEL_PRICING) {
        if (entry.pattern.test(normalized)) {
            return entry.pricing;
        }
    }
    return null;
}
function calculateUsd(tokens, usdPerMillion) {
    return (tokens * usdPerMillion) / TOKENS_PER_MILLION;
}
function getAnthropicPricing(stdin) {
    const candidates = [
        stdin.model?.display_name?.trim(),
        stdin.model?.id?.trim(),
    ];
    for (const candidate of candidates) {
        if (!candidate) {
            continue;
        }
        const pricing = matchAnthropicPricing(candidate);
        if (pricing) {
            return pricing;
        }
    }
    return null;
}
export function estimateSessionCost(stdin, sessionTokens) {
    if (!sessionTokens) {
        return null;
    }
    if (getProviderLabel(stdin)) {
        return null;
    }
    const pricing = getAnthropicPricing(stdin);
    if (!pricing) {
        return null;
    }
    const totalTokens = sessionTokens.inputTokens
        + sessionTokens.cacheCreationTokens
        + sessionTokens.cacheReadTokens
        + sessionTokens.outputTokens;
    if (totalTokens === 0) {
        return null;
    }
    const inputUsd = calculateUsd(sessionTokens.inputTokens, pricing.inputUsdPerMillion);
    const cacheCreationUsd = calculateUsd(sessionTokens.cacheCreationTokens, pricing.inputUsdPerMillion * CACHE_WRITE_MULTIPLIER);
    const cacheReadUsd = calculateUsd(sessionTokens.cacheReadTokens, pricing.inputUsdPerMillion * CACHE_READ_MULTIPLIER);
    const outputUsd = calculateUsd(sessionTokens.outputTokens, pricing.outputUsdPerMillion);
    return {
        totalUsd: inputUsd + cacheCreationUsd + cacheReadUsd + outputUsd,
        inputUsd,
        cacheCreationUsd,
        cacheReadUsd,
        outputUsd,
    };
}
function getNativeCostUsd(stdin) {
    const nativeCost = stdin.cost?.total_cost_usd;
    if (typeof nativeCost !== 'number' || !Number.isFinite(nativeCost)) {
        return null;
    }
    if (getProviderLabel(stdin)) {
        return null;
    }
    return nativeCost;
}
export function resolveSessionCost(stdin, sessionTokens) {
    const nativeCostUsd = getNativeCostUsd(stdin);
    if (nativeCostUsd !== null) {
        return {
            totalUsd: nativeCostUsd,
            source: 'native',
        };
    }
    const estimate = estimateSessionCost(stdin, sessionTokens);
    if (!estimate) {
        return null;
    }
    return {
        totalUsd: estimate.totalUsd,
        source: 'estimate',
    };
}
export function formatUsd(amount) {
    if (amount >= 1) {
        return `$${amount.toFixed(2)}`;
    }
    if (amount >= 0.1) {
        return `$${amount.toFixed(3)}`;
    }
    return `$${amount.toFixed(4)}`;
}
//# sourceMappingURL=cost.js.map