import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { LinearIcon } from "./LinearIcon";

export interface TaskboardSelectOption {
  value: string;
  label: string;
  group?: string;
  icon?: ReactNode;
  disabled?: boolean;
}

interface TaskboardSelectProps {
  value: string;
  options: TaskboardSelectOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  title?: string;
  className?: string;
  triggerClassName?: string;
  minMenuWidth?: number;
}

interface MenuPosition {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}

const VIEWPORT_GUTTER = 8;
const MENU_GAP = 4;
const MAX_MENU_HEIGHT = 280;

function enabledIndex(options: TaskboardSelectOption[], start: number, direction: 1 | -1): number {
  if (options.length === 0) return -1;
  for (let step = 0; step < options.length; step += 1) {
    const index = (start + direction * step + options.length) % options.length;
    if (!options[index]?.disabled) return index;
  }
  return -1;
}

export function TaskboardSelect({
  value,
  options,
  onChange,
  ariaLabel,
  disabled = false,
  title,
  className = "",
  triggerClassName = "",
  minMenuWidth = 176,
}: TaskboardSelectProps) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [position, setPosition] = useState<MenuPosition>({
    top: 0,
    left: 0,
    width: minMenuWidth,
    maxHeight: MAX_MENU_HEIGHT,
  });
  const selectedIndex = options.findIndex((option) => option.value === value);
  const selectedOption = options[selectedIndex] ?? options[0];

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(
      Math.max(rect.width, minMenuWidth),
      window.innerWidth - VIEWPORT_GUTTER * 2,
    );
    const estimatedHeight = Math.min(
      menuRef.current?.getBoundingClientRect().height
        ?? options.length * 30 + new Set(options.map((option) => option.group).filter(Boolean)).size * 22 + 8,
      MAX_MENU_HEIGHT,
    );
    const roomBelow = window.innerHeight - rect.bottom - VIEWPORT_GUTTER;
    const roomAbove = rect.top - VIEWPORT_GUTTER;
    const placeAbove = roomBelow < Math.min(estimatedHeight, 160) && roomAbove > roomBelow;
    const availableHeight = Math.max(96, placeAbove ? roomAbove - MENU_GAP : roomBelow - MENU_GAP);
    const maxHeight = Math.min(MAX_MENU_HEIGHT, availableHeight);
    const top = placeAbove
      ? Math.max(VIEWPORT_GUTTER, rect.top - Math.min(estimatedHeight, maxHeight) - MENU_GAP)
      : Math.min(rect.bottom + MENU_GAP, window.innerHeight - VIEWPORT_GUTTER - maxHeight);
    const left = Math.min(
      Math.max(VIEWPORT_GUTTER, rect.left),
      window.innerWidth - VIEWPORT_GUTTER - width,
    );
    setPosition({ top, left, width, maxHeight });
  }, [minMenuWidth, options]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const frame = requestAnimationFrame(updatePosition);
    return () => cancelAnimationFrame(frame);
  }, [open, updatePosition]);

  useLayoutEffect(() => {
    if (!open || activeIndex < 0) return;
    optionRefs.current[activeIndex]?.focus({ preventScroll: true });
  }, [activeIndex, open]);

  useEffect(() => {
    if (!open) return;

    function closeFromOutside(event: PointerEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    }

    function reposition() {
      updatePosition();
    }

    document.addEventListener("pointerdown", closeFromOutside);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, updatePosition]);

  function closeAndFocus() {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function choose(index: number) {
    const option = options[index];
    if (!option || option.disabled) return;
    if (option.value !== value) onChange(option.value);
    closeAndFocus();
  }

  function moveActive(direction: 1 | -1) {
    const start = activeIndex < 0 ? (direction === 1 ? 0 : options.length - 1) : activeIndex + direction;
    const nextIndex = enabledIndex(options, start, direction);
    if (nextIndex < 0) return;
    setActiveIndex(nextIndex);
  }

  function openFromKeyboard(direction: 1 | -1) {
    const start = selectedIndex >= 0 ? selectedIndex : (direction === 1 ? 0 : options.length - 1);
    setActiveIndex(enabledIndex(options, start, direction));
    setOpen(true);
  }

  function handleTriggerKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openFromKeyboard(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openFromKeyboard(-1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen((current) => !current);
    }
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      const nextIndex = enabledIndex(options, 0, 1);
      setActiveIndex(nextIndex);
    } else if (event.key === "End") {
      event.preventDefault();
      const nextIndex = enabledIndex(options, options.length - 1, -1);
      setActiveIndex(nextIndex);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(activeIndex);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeAndFocus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  const menu = open ? createPortal(
    <div
      ref={menuRef}
      id={listboxId}
      className="taskboard-select-menu"
      role="listbox"
      aria-label={ariaLabel}
      style={{
        top: position.top,
        left: position.left,
        width: position.width,
        maxHeight: position.maxHeight,
      } as CSSProperties}
      onKeyDown={handleMenuKeyDown}
    >
      {options.map((option, index) => (
        <Fragment key={option.value}>
          {option.group && option.group !== options[index - 1]?.group && (
            <div className="taskboard-select-group" role="presentation">{option.group}</div>
          )}
          <button
            ref={(element) => { optionRefs.current[index] = element; }}
            className={`taskboard-select-option${activeIndex === index ? " is-active" : ""}`}
            type="button"
            role="option"
            aria-selected={option.value === value}
            disabled={option.disabled}
            tabIndex={-1}
            onPointerMove={() => setActiveIndex(index)}
            onClick={() => choose(index)}
          >
            <span className="taskboard-select-option-icon" aria-hidden="true">{option.icon}</span>
            <span className="taskboard-select-option-label">{option.label}</span>
            <span className="taskboard-select-check" aria-hidden="true">
              {option.value === value && <LinearIcon name="check" />}
            </span>
          </button>
        </Fragment>
      ))}
    </div>,
    document.body,
  ) : null;

  return (
    <div ref={rootRef} className={`taskboard-select${className ? ` ${className}` : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className={`taskboard-select-trigger${triggerClassName ? ` ${triggerClassName}` : ""}`}
        disabled={disabled}
        title={title}
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        onClick={() => {
          if (open) setOpen(false);
          else openFromKeyboard(1);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="taskboard-select-value">{selectedOption?.label ?? ""}</span>
        <LinearIcon className="taskboard-select-chevron" name="chevronDown" />
      </button>
      {menu}
    </div>
  );
}
