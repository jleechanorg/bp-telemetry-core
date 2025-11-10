// Copyright © 2025 Sierra Labs LLC
// SPDX-License-Identifier: AGPL-3.0-only
// License-Filename: LICENSE

/**
 * Session Manager for Cursor Extension
 *
 * Manages session lifecycle and environment variables.
 * Sets CURSOR_SESSION_ID and CURSOR_WORKSPACE_HASH for hooks.
 */

import * as crypto from 'crypto';
import * as vscode from 'vscode';
import { SessionInfo } from './types';

export class SessionManager {
  private currentSession: SessionInfo | null = null;

  constructor(private context: vscode.ExtensionContext) {}

  /**
   * Start a new session
   */
  startNewSession(): SessionInfo {
    const workspacePath = this.getWorkspacePath();
    const sessionId = this.generateSessionId();
    const workspaceHash = this.computeWorkspaceHash(workspacePath);

    this.currentSession = {
      sessionId,
      workspaceHash,
      startedAt: new Date(),
      platform: 'cursor',
    };

    // Set environment variables for hooks
    this.setEnvironmentVariables(sessionId, workspaceHash);

    // Store in extension context
    this.context.workspaceState.update('currentSession', this.currentSession);

    console.log(`Started new Blueplane session: ${sessionId}`);

    return this.currentSession;
  }

  /**
   * Stop current session
   */
  stopSession(): void {
    if (this.currentSession) {
      console.log(`Stopped Blueplane session: ${this.currentSession.sessionId}`);
      this.currentSession = null;
      this.context.workspaceState.update('currentSession', null);
    }
  }

  /**
   * Get current session
   */
  getCurrentSession(): SessionInfo | null {
    return this.currentSession;
  }

  /**
   * Generate unique session ID
   * Format: curs_{timestamp}_{random}
   */
  private generateSessionId(): string {
    const timestamp = Date.now();
    const random = crypto.randomBytes(4).toString('hex');
    return `curs_${timestamp}_${random}`;
  }

  /**
   * Compute workspace hash (SHA256, truncated to 16 chars)
   */
  private computeWorkspaceHash(workspacePath: string): string {
    const hash = crypto.createHash('sha256');
    hash.update(workspacePath);
    return hash.digest('hex').substring(0, 16);
  }

  /**
   * Get workspace path
   */
  private getWorkspacePath(): string {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      return '/unknown';
    }
    return folders[0].uri.fsPath;
  }

  /**
   * Set environment variables for hooks
   *
   * Note: VSCode extensions can't directly set process env vars that
   * persist to child processes. Hooks will need to read from extension
   * storage or use alternative communication method.
   *
   * We write to a well-known file location that hooks can read.
   */
  private setEnvironmentVariables(sessionId: string, workspaceHash: string): void {
    // Store in workspace state for hooks to access
    this.context.workspaceState.update('CURSOR_SESSION_ID', sessionId);
    this.context.workspaceState.update('CURSOR_WORKSPACE_HASH', workspaceHash);

    // Write to home directory file that hooks can reliably read
    const os = require('os');
    const fs = require('fs');
    const path = require('path');

    const envFilePath = path.join(os.homedir(), '.cursor-session-env');

    const envData = {
      CURSOR_SESSION_ID: sessionId,
      CURSOR_WORKSPACE_HASH: workspaceHash,
      updated_at: new Date().toISOString(),
    };

    try {
      fs.writeFileSync(envFilePath, JSON.stringify(envData, null, 2));
      console.log(`Session environment written to ${envFilePath}`);
    } catch (error) {
      console.error('Failed to write session environment file:', error);
    }
  }

  /**
   * Show session status in status bar
   */
  showStatus(): void {
    if (!this.currentSession) {
      vscode.window.showInformationMessage('No active Blueplane session');
      return;
    }

    const duration = Date.now() - this.currentSession.startedAt.getTime();
    const durationStr = this.formatDuration(duration);

    vscode.window.showInformationMessage(
      `Blueplane Session: ${this.currentSession.sessionId}\n` +
      `Duration: ${durationStr}\n` +
      `Workspace: ${this.currentSession.workspaceHash}`
    );
  }

  /**
   * Format duration in human-readable format
   */
  private formatDuration(ms: number): string {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`;
    } else {
      return `${seconds}s`;
    }
  }
}
