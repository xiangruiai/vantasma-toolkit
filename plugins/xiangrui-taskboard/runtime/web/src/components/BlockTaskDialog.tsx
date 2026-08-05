import { useEffect, useRef, useState, type FormEvent } from "react";
import type { BlockingDraft, Task } from "../types";
import { LinearIcon } from "./LinearIcon";

interface BlockTaskDialogProps {
  task: Task;
  onCancel: () => void;
  onConfirm: (blocking: BlockingDraft) => void;
}

export function BlockTaskDialog({ task, onCancel, onConfirm }: BlockTaskDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const [reason, setReason] = useState("");
  const [unblockAction, setUnblockAction] = useState("");

  useEffect(() => {
    dialogRef.current?.showModal();
    reasonRef.current?.focus();
    return () => {
      if (dialogRef.current?.open) dialogRef.current.close();
    };
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedReason = reason.trim();
    const normalizedAction = unblockAction.trim();
    if (!normalizedReason || !normalizedAction) return;
    onConfirm({ reason: normalizedReason, unblockAction: normalizedAction });
  }

  return (
    <dialog
      ref={dialogRef}
      className="block-task-dialog"
      aria-labelledby="block-task-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <header className="block-task-dialog-header">
          <span className="block-task-dialog-icon" aria-hidden="true"><LinearIcon name="alert" /></span>
          <span>
            <small>{task.identifier}</small>
            <strong id="block-task-dialog-title">标记为已阻塞</strong>
          </span>
          <button type="button" className="icon-button" aria-label="取消" onClick={onCancel}>
            <LinearIcon name="close" />
          </button>
        </header>

        <div className="block-task-dialog-body">
          <p>这里不做 AI 推断。内容将原样保存，并记录填写人和时间。</p>
          <label>
            <span>阻塞原因</span>
            <textarea
              ref={reasonRef}
              value={reason}
              maxLength={4000}
              rows={3}
              placeholder="只写已经确认的事实，不要猜测"
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label>
            <span>需要你做什么</span>
            <textarea
              value={unblockAction}
              maxLength={4000}
              rows={3}
              placeholder="写出一个明确、可执行的解除动作"
              onChange={(event) => setUnblockAction(event.target.value)}
            />
          </label>
        </div>

        <footer>
          <button className="button secondary" type="button" onClick={onCancel}>取消</button>
          <button className="button block-confirm-button" type="submit" disabled={!reason.trim() || !unblockAction.trim()}>
            确认阻塞
          </button>
        </footer>
      </form>
    </dialog>
  );
}
