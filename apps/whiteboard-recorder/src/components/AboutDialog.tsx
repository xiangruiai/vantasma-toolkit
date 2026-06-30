import { useEffect } from 'react';
import { UI_TEXT, type LanguageCode } from '../i18n';
import './AboutDialog.css';

interface AboutDialogProps {
  language: LanguageCode;
  onClose: () => void;
  onOpenGuide: () => void;
}

function AboutDialog({ language, onClose, onOpenGuide }: AboutDialogProps) {
  const text = UI_TEXT[language].settings;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', closeOnEscape, true);
    return () => window.removeEventListener('keydown', closeOnEscape, true);
  }, [onClose]);

  return (
    <div
      className="about-dialog-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="about-dialog-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-dialog-title"
      >
        <button
          type="button"
          className="about-dialog-close"
          aria-label={text.aboutTab}
          onClick={onClose}
        >
          ×
        </button>

        <div className="about-dialog-product">
          <img
            className="about-dialog-mark"
            src="/xiangrui-logo.png"
            alt=""
            aria-hidden="true"
          />
          <div>
            <h2 id="about-dialog-title">{text.aboutTitle}</h2>
            <p className="about-dialog-description">{text.aboutDescription}</p>
          </div>
        </div>

        <section className="about-dialog-guide">
          <div>
            <h3>{text.guideTitle}</h3>
            <p>{text.guideDescription}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenGuide();
            }}
          >
            {text.guideLinkLabel}
          </button>
        </section>

        <section className="about-dialog-open-source">
          <h3>{text.openSourceTitle}</h3>
          <p>{text.openSourceIntro}</p>
          <ul>
            {text.openSourceItems.map((item) => (
              <li key={item.href}>
                <span>{item.text}</span>
                <a href={item.href} target="_blank" rel="noreferrer">
                  {item.linkLabel}
                </a>
              </li>
            ))}
          </ul>
          <p className="about-dialog-license-hint">{text.licenseFileHint}</p>
        </section>

        <section className="about-dialog-links">
          <h3>{text.productLinksTitle}</h3>
          <div>
            {text.productLinks.map((item) => (
              <a key={item.href} href={item.href} target="_blank" rel="noreferrer">
                {item.label}
              </a>
            ))}
          </div>
        </section>
      </section>
    </div>
  );
}

export default AboutDialog;
