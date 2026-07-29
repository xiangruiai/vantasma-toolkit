export interface LineDiff {
    added: number;
    deleted: number;
}
export interface TrackedFile {
    basename: string;
    fullPath: string;
    type: 'modified' | 'added' | 'deleted';
    lineDiff?: LineDiff;
}
export interface FileStats {
    modified: number;
    added: number;
    deleted: number;
    untracked: number;
    trackedFiles: TrackedFile[];
}
export interface GitStatus {
    branch: string;
    isDirty: boolean;
    ahead: number;
    behind: number;
    fileStats?: FileStats;
    lineDiff?: LineDiff;
    branchUrl?: string;
}
export declare function getGitBranch(cwd?: string): Promise<string | null>;
export declare function getGitStatus(cwd?: string): Promise<GitStatus | null>;
//# sourceMappingURL=git.d.ts.map