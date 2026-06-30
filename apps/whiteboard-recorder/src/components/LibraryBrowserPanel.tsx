import { useCallback, useEffect, useMemo, useState } from 'react';
import './LibraryBrowserPanel.css';
import { UI_TEXT, type LanguageCode } from '../i18n';

const LIBRARY_ORIGIN = 'https://libraries.excalidraw.com';

type SortMode = 'default' | 'new' | 'updated' | 'week' | 'author' | 'name';

interface LibraryAuthor {
  name: string;
  url?: string;
}

interface RemoteLibrary {
  name: string;
  description: string;
  authors: LibraryAuthor[];
  source: string;
  preview: string;
  created: string;
  updated?: string;
  version?: number;
}

interface LibraryStats {
  total: number;
  week: number;
}

interface LibraryItem extends RemoteLibrary {
  id: string;
  downloads: LibraryStats;
}

interface LibraryBrowserPanelProps {
  url: string;
  language: LanguageCode;
  isPinned: boolean;
  onAddLibrary: (source: string) => Promise<void>;
  onClose: () => void;
  onPinnedChange: (isPinned: boolean) => void;
}

const getLibraryId = (source: string) => {
  return source.toLowerCase().replace(/\//g, '-').replace(/\.excalidrawlib$/, '');
};

const getDateTime = (value?: string) => {
  const time = value ? new Date(value).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
};

function LibraryBrowserPanel({
  url,
  language,
  isPinned,
  onAddLibrary,
  onClose,
  onPinnedChange,
}: LibraryBrowserPanelProps) {
  const text = UI_TEXT[language].libraryPanel;
  const [libraries, setLibraries] = useState<LibraryItem[]>([]);
  const [query, setQuery] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('default');
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [addingSource, setAddingSource] = useState<string | null>(null);
  const [previewFailures, setPreviewFailures] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  const loadLibraries = useCallback(async (signal?: AbortSignal, refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const cacheBust = refresh ? `?t=${Date.now()}` : '';
      const [librariesResponse, statsResponse] = await Promise.all([
        fetch(`${LIBRARY_ORIGIN}/libraries.json${cacheBust}`, { signal }),
        fetch(`${LIBRARY_ORIGIN}/stats.json${cacheBust}`, { signal }),
      ]);

      if (!librariesResponse.ok || !statsResponse.ok) {
        throw new Error(text.error);
      }

      const remoteLibraries = await librariesResponse.json() as RemoteLibrary[];
      const stats = await statsResponse.json() as Record<string, LibraryStats>;
      const nextLibraries = remoteLibraries.map((library) => {
        const id = getLibraryId(library.source);
        return {
          ...library,
          id,
          downloads: stats[id] || { total: 0, week: 0 },
        };
      });

      setLibraries(nextLibraries);
      if (refresh) {
        setPreviewFailures({});
      }
    } catch (loadError) {
      if ((loadError as Error).name !== 'AbortError') {
        setError(text.error);
      }
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [text.error]);

  useEffect(() => {
    const controller = new AbortController();
    loadLibraries(controller.signal);

    return () => controller.abort();
  }, [loadLibraries]);

  const visibleLibraries = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = normalizedQuery
      ? libraries.filter((library) => {
          const authors = library.authors.map((author) => author.name).join(' ');
          return [
            library.name,
            library.description,
            authors,
            library.source,
          ].some((value) => value.toLowerCase().includes(normalizedQuery));
        })
      : libraries;

    return [...filtered].sort((a, b) => {
      switch (sortMode) {
        case 'new':
          return getDateTime(b.created) - getDateTime(a.created);
        case 'updated':
          return getDateTime(b.updated || b.created) - getDateTime(a.updated || a.created);
        case 'week':
          return b.downloads.week - a.downloads.week;
        case 'author':
          return (a.authors[0]?.name || '').localeCompare(b.authors[0]?.name || '');
        case 'name':
          return a.name.localeCompare(b.name);
        case 'default':
        default:
          return b.downloads.total - a.downloads.total;
      }
    });
  }, [libraries, query, sortMode]);

  const makeLibraryFileUrl = (source: string) => {
    return `${LIBRARY_ORIGIN}/libraries/${source}`;
  };

  const makePreviewUrl = (library: LibraryItem) => {
    const failureCount = previewFailures[library.id] || 0;
    const baseUrl = `${LIBRARY_ORIGIN}/libraries/${library.preview}`;
    return failureCount === 0
      ? `${baseUrl}?v=${encodeURIComponent(library.updated || library.created || library.id)}`
      : baseUrl;
  };

  const formatDate = (value?: string) => {
    if (!value) return '';

    return new Intl.DateTimeFormat(language === 'zh-CN' ? 'zh-CN' : 'en', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }).format(new Date(value));
  };

  const refreshLibraries = () => {
    loadLibraries(undefined, true);
  };

  const handleAddLibrary = async (source: string) => {
    setAddingSource(source);
    setError(null);
    try {
      await onAddLibrary(source);
    } catch {
      setError(text.addError);
    } finally {
      setAddingSource(null);
    }
  };

  const handlePreviewError = (id: string) => {
    setPreviewFailures((previous) => ({
      ...previous,
      [id]: (previous[id] || 0) + 1,
    }));
  };

  return (
    <aside
      className={`library-browser-panel ${isPinned ? 'pinned' : ''}`}
      aria-label={text.title}
    >
      <header className="library-browser-header">
        <div className="library-browser-tabs" aria-label={text.title}>
          <button type="button" className="library-browser-tab" aria-label={text.searchTab} title={text.searchTab}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
          <button type="button" className="library-browser-tab active" aria-label={text.libraryTab} title={text.libraryTab}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </button>
        </div>
        <div className="library-browser-actions">
          <button
            type="button"
            className={`library-browser-icon-btn ${isRefreshing ? 'spinning' : ''}`}
            onClick={refreshLibraries}
            disabled={isRefreshing}
            aria-label={text.refresh}
            title={text.refresh}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
              <path d="M3 21v-5h5" />
              <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
          </button>
          <button
            type="button"
            className={`library-browser-icon-btn ${isPinned ? 'active' : ''}`}
            onClick={() => onPinnedChange(!isPinned)}
            aria-pressed={isPinned}
            aria-label={isPinned ? text.unpin : text.pin}
            title={isPinned ? text.unpin : text.pin}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 17v5" />
              <path d="M5 17h14" />
              <path d="M7 17 9 4h6l2 13" />
              <path d="M9 4h6" />
            </svg>
          </button>
          <button
            type="button"
            className="library-browser-icon-btn"
            onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}
            aria-label={text.openExternal}
            title={text.openExternal}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 3h6v6" />
              <path d="M10 14 21 3" />
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            </svg>
          </button>
          <button
            type="button"
            className="library-browser-icon-btn"
            onClick={onClose}
            aria-label={text.close}
            title={text.close}
          >
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
      </header>

      <div className="library-browser-title">
        <p>{text.eyebrow}</p>
        <h2>{text.title}</h2>
      </div>

      <div className="library-browser-controls">
        <label className="library-browser-search">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={text.searchPlaceholder}
          />
        </label>
        <label className="library-browser-sort">
          <span>{text.sortLabel}</span>
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
            <option value="default">{text.sortDefault}</option>
            <option value="new">{text.sortNew}</option>
            <option value="updated">{text.sortUpdated}</option>
            <option value="week">{text.sortWeek}</option>
            <option value="author">{text.sortAuthor}</option>
            <option value="name">{text.sortName}</option>
          </select>
        </label>
      </div>

      <div className="library-browser-count">
        {isLoading ? text.loading : `${visibleLibraries.length} ${text.results}`}
      </div>

      <div className="library-browser-list">
        {error && (
          <div className="library-browser-state">
            <p>{error}</p>
            <button type="button" onClick={refreshLibraries}>{text.retry}</button>
          </div>
        )}

        {!error && !isLoading && visibleLibraries.length === 0 && (
          <div className="library-browser-state">
            <p>{text.empty}</p>
          </div>
        )}

        {!error && isLoading && (
          <div className="library-browser-state">
            <p>{text.loading}</p>
          </div>
        )}

        {!error && !isLoading && (
          <div className="library-rows">
            {visibleLibraries.map((library) => (
              <article className="library-row" key={library.id}>
                <button
                  type="button"
                  className="library-row-preview"
                  onClick={() => handleAddLibrary(library.source)}
                  disabled={addingSource !== null}
                  title={`${text.add}: ${library.name}`}
                >
                  {(previewFailures[library.id] || 0) > 1 ? (
                    <span className="library-row-fallback">{library.name.slice(0, 2)}</span>
                  ) : (
                    <img
                      src={makePreviewUrl(library)}
                      alt={library.name}
                      loading="lazy"
                      crossOrigin="anonymous"
                      referrerPolicy="no-referrer"
                      onError={() => handlePreviewError(library.id)}
                    />
                  )}
                </button>
                <div className="library-row-body">
                  <div className="library-row-title">
                    <h3>{library.name}</h3>
                    <span>{library.downloads.total.toLocaleString()}</span>
                  </div>
                  <p className="library-row-author">
                    {library.authors.map((author) => author.name).join(', ')}
                  </p>
                  <p className="library-row-description">{library.description}</p>
                  <div className="library-row-footer">
                    <button
                      type="button"
                      onClick={() => handleAddLibrary(library.source)}
                      disabled={addingSource !== null}
                    >
                      {addingSource === library.source ? text.adding : text.add}
                    </button>
                    <a href={makeLibraryFileUrl(library.source)} download title={text.download}>
                      {text.download}
                    </a>
                    <span>{text.created}: {formatDate(library.created)}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

export default LibraryBrowserPanel;
