import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { UI_TEXT, type LanguageCode } from '../i18n';
import {
  SHORTCUT_GROUPS,
  formatShortcut,
  type ShortcutActionId,
  type ShortcutGroupId,
  type ShortcutSettings,
} from '../shortcuts';
import './ExcalidrawHelpCloseButton.css';

interface ExcalidrawHelpCloseButtonProps {
  language: LanguageCode;
  label: string;
  onClose: () => void;
  shortcuts: ShortcutSettings;
}

const nativeHelpExternalLinkLabels = [
  '文档',
  '浏览我们的博客',
  '发现问题',
  '提交反馈',
  'youtube',
  'documentation',
  'docs',
  'blog',
  'found an issue',
  'submit feedback',
];

const hideNativeHelpExternalLinks = (content: HTMLElement | null) => {
  if (!content) {
    return;
  }

  Array.from(content.children).forEach((child) => {
    if (!(child instanceof HTMLElement) || child.classList.contains('excalidraw-help-shortcuts-host')) {
      return;
    }

    const label = child.textContent?.replace(/\s+/g, ' ').trim().toLowerCase() || '';
    const linkCount = child.querySelectorAll('a, button').length;
    const shouldHide = linkCount >= 2
      && nativeHelpExternalLinkLabels.some((linkLabel) => label.includes(linkLabel));

    child.classList.toggle('excalidraw-help-native-links-hidden', shouldHide);
  });
};

const getShortcutHost = (content: HTMLElement | null) => {
  if (!content) {
    return null;
  }

  const children = Array.from(content.children) as HTMLElement[];
  const existingHost = children.find((child) => (
    child.classList.contains('excalidraw-help-shortcuts-host')
  ));
  const nativeShortcutIndex = children.findIndex((child) => {
    if (child.classList.contains('excalidraw-help-shortcuts-host')) {
      return false;
    }

    const label = child.textContent?.trim() || '';
    const normalizedLabel = label.toLowerCase();
    return label.includes('快捷键列表')
      || normalizedLabel === 'shortcuts'
      || normalizedLabel.includes('shortcuts list')
      || normalizedLabel.includes('keyboard shortcuts');
  });
  const host = existingHost || document.createElement('div');

  host.className = 'excalidraw-help-shortcuts-host';

  if (nativeShortcutIndex >= 0) {
    const anchor = children[nativeShortcutIndex];

    if (host.parentElement !== content || host.nextElementSibling !== anchor) {
      content.insertBefore(host, anchor);
    }
  } else if (!existingHost) {
    content.appendChild(host);
  }

  const hostIndex = Array.from(content.children).indexOf(host);

  Array.from(content.children).forEach((child, index) => {
    if (child === host) {
      return;
    }

    const shouldHide = hostIndex >= 0 && index > hostIndex;

    if (shouldHide && !child.classList.contains('excalidraw-help-native-shortcuts-hidden')) {
      child.classList.add('excalidraw-help-native-shortcuts-hidden');
    } else if (!shouldHide && child.classList.contains('excalidraw-help-native-shortcuts-hidden')) {
      child.classList.remove('excalidraw-help-native-shortcuts-hidden');
    }
  });

  return host;
};

function ExcalidrawHelpCloseButton({
  language,
  label,
  onClose,
  shortcuts,
}: ExcalidrawHelpCloseButtonProps) {
  const text = UI_TEXT[language].settings;
  const shortcutGroupLabels = text.shortcutGroups as Record<ShortcutGroupId, string>;
  const shortcutActionLabels = text.shortcutActions as Record<ShortcutActionId, string>;
  const [closeTarget, setCloseTarget] = useState<HTMLElement | null>(null);
  const [shortcutHost, setShortcutHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let animationFrame = 0;

    const updateTargets = () => {
      const nextCloseTarget = document.querySelector<HTMLElement>(
        '.excalidraw-modal-container .Modal.HelpDialog .Island',
      );
      const helpContent = document.querySelector<HTMLElement>(
        '.excalidraw-modal-container .Modal.HelpDialog .Dialog__content',
      );
      hideNativeHelpExternalLinks(helpContent);
      const nextShortcutHost = getShortcutHost(
        helpContent,
      );

      setCloseTarget((currentTarget) => (currentTarget === nextCloseTarget ? currentTarget : nextCloseTarget));
      setShortcutHost((currentTarget) => (currentTarget === nextShortcutHost ? currentTarget : nextShortcutHost));
    };

    const scheduleUpdateTargets = () => {
      if (animationFrame) {
        return;
      }

      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = 0;
        updateTargets();
      });
    };

    updateTargets();

    const observer = new MutationObserver(scheduleUpdateTargets);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      if (animationFrame) {
        window.cancelAnimationFrame(animationFrame);
      }
      observer.disconnect();
    };
  }, [language]);

  return (
    <>
      {shortcutHost && createPortal(
        <section className="excalidraw-help-shortcuts-section">
          <div className="excalidraw-help-shortcuts-heading">
            <h3>{text.helpShortcutsTitle}</h3>
            <p>{text.helpShortcutsDescription}</p>
          </div>
          <div className="excalidraw-help-shortcuts-grid">
            {SHORTCUT_GROUPS.map((group) => (
              <div className="excalidraw-help-shortcuts-card" key={group.id}>
                <h4>{shortcutGroupLabels[group.id]}</h4>
                <div className="excalidraw-help-shortcuts-list">
                  {group.actions.map((action) => (
                    <div className="excalidraw-help-shortcut-row" key={action}>
                      <span>{shortcutActionLabels[action]}</span>
                      <kbd>{formatShortcut(shortcuts[action], language)}</kbd>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>,
        shortcutHost,
      )}
      {closeTarget && createPortal(
        <button
          type="button"
          className="excalidraw-help-close-button"
          aria-label={label}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onClose();
          }}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M6 6l12 12" />
            <path d="M18 6L6 18" />
          </svg>
        </button>,
        closeTarget,
      )}
    </>
  );
}

export default ExcalidrawHelpCloseButton;
