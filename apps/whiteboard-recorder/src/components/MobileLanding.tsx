/**
 * MobileLanding - Shown to mobile users instead of the main app
 *
 * The recorder currently depends on computer web browser APIs and layout.
 * Mobile visitors see a lightweight product notice with share/copy actions.
 */

import { useEffect } from 'react';
import './MobileLanding.css';
import { UI_TEXT, type LanguageCode } from '../i18n';

interface MobileLandingProps {
  language: LanguageCode;
  onLanguageChange: (language: LanguageCode) => void;
}

function MobileLanding({ language, onLanguageChange }: MobileLandingProps) {
  const text = UI_TEXT[language];

  const appUrl = window.location.href;

  // Override global overflow:hidden to allow scrolling on mobile
  useEffect(() => {
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
    return () => {
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    };
  }, []);

  const handleShare = async () => {
    if ('share' in navigator) {
      try {
        await navigator.share({
          title: text.common.appName,
          text: text.mobile.shareText,
          url: appUrl,
        });
      } catch {
        // User cancelled or share failed - that's fine
      }
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(appUrl);
      alert(text.alerts.linkCopied);
    } catch {
      // Fallback for older browsers
      prompt(text.alerts.copyPrompt, appUrl);
    }
  };

  return (
    <div className="mobile-landing">
      {/* Ambient background */}
      <div className="mobile-bg" />

      <div className="mobile-content">
        <div className="mobile-language-switcher">
          <button
            className={language === 'zh-CN' ? 'active' : ''}
            onClick={() => onLanguageChange('zh-CN')}
            aria-label={text.language.ariaLabel}
          >
            {text.language.zh}
          </button>
          <button
            className={language === 'en' ? 'active' : ''}
            onClick={() => onLanguageChange('en')}
            aria-label={text.language.ariaLabel}
          >
            {text.language.en}
          </button>
        </div>

        <section className="mobile-card" aria-labelledby="mobile-title">
          <div className="mobile-icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="7" y="8" width="34" height="25" rx="5" stroke="currentColor" strokeWidth="2.6"/>
            <path d="M14 17h12M14 23h8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"/>
            <circle cx="33" cy="27" r="5.5" fill="currentColor"/>
            <circle cx="33" cy="27" r="2" fill="white"/>
            <path d="M17 39h14" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round"/>
          </svg>
          </div>

          <p className="mobile-kicker">{text.common.appName}</p>

          <h1 id="mobile-title" className="mobile-headline">
            {text.mobile.title}
          </h1>

          <p className="mobile-subheadline">
            {text.mobile.description}
          </p>

          <div className="mobile-notice">
            <span className="notice-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <rect x="4" y="5" width="16" height="11" rx="2" stroke="currentColor" strokeWidth="2"/>
                <path d="M9 20h6M12 16v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </span>
            <span>{text.mobile.desktopRequired}</span>
          </div>

          <div className="mobile-actions">
            <p className="mobile-actions-label">{text.mobile.actionsLabel}</p>
            <div className="mobile-action-buttons">
              {'share' in navigator && (
                <button className="mobile-action-btn primary" onClick={handleShare}>
                  <span aria-hidden="true">↗</span> {text.mobile.share}
                </button>
              )}
              <button className="mobile-action-btn" onClick={handleCopy}>
                <span aria-hidden="true">⎘</span> {text.mobile.copyLink}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default MobileLanding;
