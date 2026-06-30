import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import './GlobalTooltip.css';

type TooltipPlacement = 'top' | 'bottom';
type TooltipSize = {
  width: number;
  height: number;
};

type TooltipState = {
  label: string;
  left: number;
  top: number;
  placement: TooltipPlacement;
};

const TOOLTIP_SELECTOR = '[data-tooltip], [data-excalicord-title], [title], [aria-label]';
const TITLE_STORE_ATTR = 'data-excalicord-title';
const HOVER_DELAY = 180;
const GAP = 10;
const EDGE_PADDING = 12;

const clamp = (value: number, min: number, max: number) => {
  if (max < min) {
    return (min + max) / 2;
  }

  return Math.min(Math.max(value, min), max);
};

const getElementLabel = (element: Element) => {
  const dataTooltip = element.getAttribute('data-tooltip')?.trim();
  if (dataTooltip) {
    return dataTooltip;
  }

  const ariaLabel = element.getAttribute('aria-label')?.trim();
  const visibleText = element.textContent?.replace(/\s+/g, ' ').trim() || '';
  const isInteractive = element.matches('button, a, input, select, textarea, [role="button"], [role="menuitem"]');

  if (ariaLabel && isInteractive && (!visibleText || visibleText === ariaLabel)) {
    return ariaLabel;
  }

  const childAriaLabel = element
    .querySelector('button[aria-label], input[aria-label], a[aria-label], [role="button"][aria-label], [role="menuitem"][aria-label]')
    ?.getAttribute('aria-label')
    ?.trim();
  if (childAriaLabel && (!visibleText || visibleText === childAriaLabel)) {
    return childAriaLabel;
  }

  const title = element.getAttribute('title')?.trim();
  if (title) {
    return title;
  }

  const storedTitle = element.getAttribute(TITLE_STORE_ATTR)?.trim();
  if (storedTitle) {
    return storedTitle;
  }

  return '';
};

const findTooltipElement = (start: EventTarget | null) => {
  if (!(start instanceof Element)) {
    return null;
  }

  const element = start.closest<HTMLElement>(TOOLTIP_SELECTOR);
  if (!element || element.closest('.global-native-tooltip')) {
    return null;
  }

  return getElementLabel(element) ? element : null;
};

const getTooltipPosition = (target: Element, tooltipSize?: TooltipSize): Omit<TooltipState, 'label'> => {
  const rect = target.getBoundingClientRect();
  const measuredWidth = tooltipSize?.width ?? 0;
  const measuredHeight = tooltipSize?.height ?? 44;
  let placement: TooltipPlacement = (
    rect.bottom + GAP + measuredHeight > window.innerHeight - EDGE_PADDING
      ? 'top'
      : 'bottom'
  );

  if (
    placement === 'top' &&
    rect.top - GAP - measuredHeight < EDGE_PADDING &&
    rect.bottom + GAP + measuredHeight <= window.innerHeight - EDGE_PADDING
  ) {
    placement = 'bottom';
  }

  const top = placement === 'bottom'
    ? clamp(rect.bottom + GAP, EDGE_PADDING, window.innerHeight - EDGE_PADDING - measuredHeight)
    : clamp(rect.top - GAP, EDGE_PADDING + measuredHeight, window.innerHeight - EDGE_PADDING);
  const left = clamp(
    rect.left + rect.width / 2,
    EDGE_PADDING + measuredWidth / 2,
    window.innerWidth - EDGE_PADDING - measuredWidth / 2,
  );

  return {
    left,
    top,
    placement,
  };
};

function GlobalTooltip() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const activeElementRef = useRef<Element | null>(null);
  const showTimerRef = useRef<number | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const clearShowTimer = useCallback(() => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
  }, []);

  const hideTooltip = useCallback(() => {
    clearShowTimer();
    activeElementRef.current = null;
    setTooltip(null);
  }, [clearShowTimer]);

  const showTooltip = useCallback((element: Element) => {
    const label = getElementLabel(element);
    if (!label) {
      hideTooltip();
      return;
    }

    clearShowTimer();
    activeElementRef.current = element;

    showTimerRef.current = window.setTimeout(() => {
      setTooltip({
        label,
        ...getTooltipPosition(element),
      });
    }, HOVER_DELAY);
  }, [clearShowTimer, hideTooltip]);

  useLayoutEffect(() => {
    const activeElement = activeElementRef.current;
    const tooltipElement = tooltipRef.current;

    if (!tooltip || !activeElement || !tooltipElement) {
      return;
    }

    const tooltipRect = tooltipElement.getBoundingClientRect();
    const nextPosition = getTooltipPosition(activeElement, {
      width: tooltipRect.width,
      height: tooltipRect.height,
    });

    setTooltip((currentTooltip) => {
      if (!currentTooltip) {
        return currentTooltip;
      }

      if (
        currentTooltip.placement === nextPosition.placement &&
        Math.abs(currentTooltip.left - nextPosition.left) < 0.5 &&
        Math.abs(currentTooltip.top - nextPosition.top) < 0.5
      ) {
        return currentTooltip;
      }

      return {
        ...currentTooltip,
        ...nextPosition,
      };
    });
  }, [tooltip]);

  useEffect(() => {
    const scrubNativeTitles = (root: ParentNode = document) => {
      root.querySelectorAll?.('[title]').forEach((element) => {
        if (!(element instanceof Element) || element.closest('.global-native-tooltip')) {
          return;
        }

        const title = element.getAttribute('title')?.trim();
        if (!title) {
          element.removeAttribute('title');
          return;
        }

        if (!element.hasAttribute(TITLE_STORE_ATTR)) {
          element.setAttribute(TITLE_STORE_ATTR, title);
        }

        if (!element.hasAttribute('aria-label') && element.matches('button, a, input, select, textarea, [role="button"], [role="menuitem"]')) {
          element.setAttribute('aria-label', title);
        }

        element.removeAttribute('title');
      });
    };

    scrubNativeTitles();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'attributes') {
          const target = mutation.target;
          if (target instanceof Element) {
            scrubNativeTitles(target.parentElement ?? document);
          }
          continue;
        }

        mutation.addedNodes.forEach((node) => {
          if (node instanceof Element) {
            scrubNativeTitles(node);
            if (node.hasAttribute('title')) {
              scrubNativeTitles(node.parentElement ?? document);
            }
          }
        });
      }
    });

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['title'],
    });

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const handlePointerOver = (event: PointerEvent) => {
      const element = findTooltipElement(event.target);
      if (!element || element === activeElementRef.current) {
        return;
      }

      showTooltip(element);
    };

    const handlePointerOut = (event: PointerEvent) => {
      const activeElement = activeElementRef.current;
      const nextTarget = event.relatedTarget;

      if (
        activeElement &&
        nextTarget instanceof Node &&
        activeElement.contains(nextTarget)
      ) {
        return;
      }

      hideTooltip();
    };

    const handleFocusIn = (event: FocusEvent) => {
      const element = findTooltipElement(event.target);
      if (element) {
        showTooltip(element);
      }
    };

    const handleFocusOut = () => hideTooltip();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        hideTooltip();
      }
    };

    const updateTooltipPosition = () => {
      const activeElement = activeElementRef.current;
      if (!activeElement) {
        return;
      }

      const tooltipRect = tooltipRef.current?.getBoundingClientRect();
      const nextPosition = getTooltipPosition(
        activeElement,
        tooltipRect
          ? { width: tooltipRect.width, height: tooltipRect.height }
          : undefined,
      );

      setTooltip((currentTooltip) => (
        currentTooltip
          ? {
            ...currentTooltip,
            ...nextPosition,
          }
          : currentTooltip
      ));
    };

    document.addEventListener('pointerover', handlePointerOver, true);
    document.addEventListener('pointerout', handlePointerOut, true);
    document.addEventListener('focusin', handleFocusIn, true);
    document.addEventListener('focusout', handleFocusOut, true);
    document.addEventListener('keydown', handleKeyDown, true);
    window.addEventListener('scroll', hideTooltip, true);
    window.addEventListener('resize', updateTooltipPosition);

    return () => {
      document.removeEventListener('pointerover', handlePointerOver, true);
      document.removeEventListener('pointerout', handlePointerOut, true);
      document.removeEventListener('focusin', handleFocusIn, true);
      document.removeEventListener('focusout', handleFocusOut, true);
      document.removeEventListener('keydown', handleKeyDown, true);
      window.removeEventListener('scroll', hideTooltip, true);
      window.removeEventListener('resize', updateTooltipPosition);
      hideTooltip();
    };
  }, [hideTooltip, showTooltip]);

  if (!tooltip) {
    return null;
  }

  return (
    <div
      ref={tooltipRef}
      className={`global-native-tooltip ${tooltip.placement}`}
      role="tooltip"
      style={{
        left: tooltip.left,
        top: tooltip.top,
      }}
    >
      {tooltip.label}
    </div>
  );
}

export default GlobalTooltip;
