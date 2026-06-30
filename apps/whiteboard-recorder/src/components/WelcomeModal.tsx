/**
 * WelcomeModal - Shows once on first visit to explain what the app does
 *
 * Stored in localStorage so returning users go straight to the app.
 */

import { useCallback, useState, useEffect } from 'react';
import './WelcomeModal.css';
import { trackWelcomeModalDismissed } from '../utils/analytics';
import { UI_TEXT, type LanguageCode } from '../i18n';

const STORAGE_KEY = 'excalicord_welcomed';

interface WelcomeModalProps {
  language: LanguageCode;
}

function WelcomeModal({ language }: WelcomeModalProps) {
  const text = UI_TEXT[language].welcome;
  const [isVisible, setIsVisible] = useState(() => {
    try {
      return !localStorage.getItem(STORAGE_KEY);
    } catch {
      return true;
    }
  });

  const handleDismiss = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, 'true');
    setIsVisible(false);
    trackWelcomeModalDismissed();
  }, []);

  // Dismiss on Escape key
  useEffect(() => {
    if (!isVisible) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleDismiss();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleDismiss, isVisible]);

  if (!isVisible) return null;

  return (
    <div className="welcome-overlay" onClick={handleDismiss}>
      <div className="welcome-modal" onClick={e => e.stopPropagation()}>
        {/* App icon - whiteboard with webcam bubble inside */}
        <div className="welcome-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="4" y="6" width="40" height="30" rx="4" stroke="currentColor" strokeWidth="2.5"/>
            <circle cx="34" cy="26" r="7" fill="#ef4444"/>
            <circle cx="34" cy="26" r="3" fill="white"/>
            <path d="M12 16h14M12 22h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>

        <h1 className="welcome-title">{text.title}</h1>

        <p className="welcome-subtitle">
          {text.subtitle}
        </p>

        {/* Quick feature list */}
        <div className="welcome-features">
          <div className="welcome-feature">
            <span className="feature-icon">🎨</span>
            <span>{text.features[0]}</span>
          </div>
          <div className="welcome-feature">
            <span className="feature-icon">📹</span>
            <span>{text.features[1]}</span>
          </div>
          <div className="welcome-feature">
            <span className="feature-icon">📜</span>
            <span>{text.features[2]}</span>
          </div>
          <div className="welcome-feature">
            <span className="feature-icon">⏺️</span>
            <span>{text.features[3]}</span>
          </div>
        </div>

        {/* CTA */}
        <button className="welcome-cta" onClick={handleDismiss}>
          {text.cta}
        </button>

        <p className="welcome-hint">
          {text.hintPrefix} <kbd>Esc</kbd> {text.hintSuffix}
        </p>
      </div>
    </div>
  );
}

export default WelcomeModal;
