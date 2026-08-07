const BUILD_REFRESH_PARAM = "__codex_taskboard_refresh";

interface BuildIndexResponse {
  ok: boolean;
  text: () => Promise<string>;
}

interface BuildLocation {
  href: string;
  origin: string;
  replace: (url: string) => void;
}

interface BuildRecoveryOptions {
  currentAssetUrls?: string[];
  fetchImpl?: (url: string, init: RequestInit) => Promise<BuildIndexResponse>;
  locationRef?: BuildLocation;
  now?: () => number;
}

function normalizeAssetPaths(urls: string[], origin: string): string[] {
  return urls.flatMap((url) => {
    try {
      const parsed = new URL(url, origin);
      return parsed.pathname.includes("/assets/") ? [parsed.pathname] : [];
    } catch {
      return [];
    }
  }).sort();
}

function assetUrlsFromDocument(): string[] {
  return Array.from(document.querySelectorAll<HTMLScriptElement | HTMLLinkElement>(
    'script[src], link[rel="stylesheet"][href]',
  )).map((element) => element instanceof HTMLScriptElement ? element.src : element.href);
}

function assetUrlsFromIndex(html: string): string[] {
  return Array.from(html.matchAll(/(?:src|href)=["']([^"']*\/assets\/[^"']+)["']/g))
    .map((match) => match[1]);
}

export async function reloadIfTaskboardBuildStale(
  options: BuildRecoveryOptions = {},
): Promise<boolean> {
  const locationRef = options.locationRef ?? window.location;
  const currentAssets = normalizeAssetPaths(
    options.currentAssetUrls ?? assetUrlsFromDocument(),
    locationRef.origin,
  );
  if (currentAssets.length === 0) return false;

  const now = options.now ?? Date.now;
  const response = await (options.fetchImpl ?? fetch)(
    `${locationRef.origin}/?__taskboard_build_check=${now()}`,
    { cache: "no-store" },
  );
  if (!response.ok) return false;

  const latestAssets = normalizeAssetPaths(
    assetUrlsFromIndex(await response.text()),
    locationRef.origin,
  );
  if (latestAssets.length === 0 || latestAssets.join("\n") === currentAssets.join("\n")) {
    return false;
  }

  const replacement = new URL(locationRef.href);
  replacement.searchParams.set(BUILD_REFRESH_PARAM, `build-${now().toString(36)}`);
  locationRef.replace(replacement.href);
  return true;
}
