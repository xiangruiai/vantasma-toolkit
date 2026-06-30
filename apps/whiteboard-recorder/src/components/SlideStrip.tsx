import './SlideStrip.css';
import { UI_TEXT, type LanguageCode } from '../i18n';

export type SlideFrameItem = {
  id: string;
  name: string | null;
};

interface SlideStripProps {
  slides: SlideFrameItem[];
  currentSlideIndex: number;
  isRecording: boolean;
  isPreviewing: boolean;
  settingsOpen: boolean;
  language: LanguageCode;
  onAddSlide: () => void;
  onGoToSlide: (index: number) => void;
  onDeleteSlide: (index: number) => void;
}

function SlideStrip({
  slides,
  currentSlideIndex,
  isRecording,
  isPreviewing,
  settingsOpen,
  language,
  onAddSlide,
  onGoToSlide,
  onDeleteSlide,
}: SlideStripProps) {
  const text = UI_TEXT[language].slides;
  const hasSlides = slides.length > 0;
  const canAdd = !isRecording;
  const canDelete = !isRecording && !isPreviewing;

  if (settingsOpen || (isRecording && !hasSlides)) {
    return null;
  }

  return (
    <aside className="slide-strip" aria-label={text.label}>
      {hasSlides && (
        <>
          <div className="slide-strip-header" aria-live="polite">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <rect x="4" y="5" width="16" height="12" rx="2" />
              <path d="M8 3v2" />
              <path d="M16 3v2" />
            </svg>
            <span>
              {isRecording
                ? text.counter
                    .replace('{{current}}', String(currentSlideIndex + 1))
                    .replace('{{total}}', String(slides.length))
                : text.label}
            </span>
          </div>

          <div className="slide-strip-list">
            {slides.map((slide, index) => (
              <button
                key={slide.id}
                type="button"
                className={`slide-strip-page ${index === currentSlideIndex ? 'active' : ''}`}
                aria-current={index === currentSlideIndex ? 'page' : undefined}
                aria-label={text.goTo.replace('{{index}}', String(index + 1))}
                data-tooltip={slide.name || text.goTo.replace('{{index}}', String(index + 1))}
                onClick={() => onGoToSlide(index)}
              >
                <span>{index + 1}</span>
                {canDelete && (
                  <span
                    role="button"
                    tabIndex={0}
                    className="slide-strip-delete"
                    aria-label={text.delete}
                    data-tooltip={text.delete}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDeleteSlide(index);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        event.stopPropagation();
                        onDeleteSlide(index);
                      }
                    }}
                  >
                    <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
                      <path d="M3 3l6 6" />
                      <path d="M9 3 3 9" />
                    </svg>
                  </span>
                )}
              </button>
            ))}
          </div>
        </>
      )}

      {hasSlides && canAdd && <div className="slide-strip-divider" />}

      {canAdd && (
        <button
          type="button"
          className={`slide-strip-add ${hasSlides ? '' : 'empty'}`}
          aria-label={text.add}
          data-tooltip={hasSlides ? undefined : text.firstSlideTooltip}
          onClick={onAddSlide}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M12 5v14" />
            <path d="M5 12h14" />
          </svg>
        </button>
      )}
    </aside>
  );
}

export default SlideStrip;
